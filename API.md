# API Documentation — HTQWeb Platform

> **State: post-cutover (phase 11 complete).** The nine FastAPI microservices
> and the Django monolith that preceded them are both gone. One Django
> backend (Python 3.14, Django 5.2.7) now serves every domain behind a Vite
> dev proxy (`:3000`) or the nginx prod gateway (`:80`). Real-time chat over
> Socket.IO, served by the backend's ASGI process. One Postgres schema.

## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│ Browser                                                               │
└─────────┬─────────────────────────────────────────────────────────────┘
          │  HTTP (no TLS in dev)
          ▼
┌──────────────────────────────────────────────────────────────────────┐
│ Edge                                                                  │
│   dev:  Vite dev server :3000   (frontend container, HMR)             │
│   prod: nginx :80               (frontend static + proxy)             │
└─────────┬────────────────────────────────────────────────────────────┘
          │  Proxy by URL prefix
          ▼
┌──────────────────────────────────────────────────────────────────────┐
│ One Django backend (Docker network — not directly user-reachable     │
│ in prod), same image, different `command` per process:               │
│                                                                       │
│   backend-web    :8000   gunicorn/WSGI — all of /api/*, /django-admin/,│
│                          static. Only this process runs `migrate` +   │
│                          seeds the admin account (RUN_MIGRATIONS=1)   │
│   backend-asgi   :8000   uvicorn/ASGI  — SSE /api/requests/v1/stream +│
│                          WebSocket /ws/ (messenger Socket.IO)         │
│   backend-worker         Celery worker (all domains' @shared_task)   │
│   backend-beat           Celery beat (django-celery-beat schedule)   │
│   flower         :5555   Celery monitoring UI                        │
└─────────┬────────────────────────────────────────────────────────────┘
          │
          ▼
┌──────────────────────────────────────────────────────────────────────┐
│ Postgres :5432 (direct — no pooling middleman in the request path)   │
│   one schema: public. Table names are Django's own default           │
│   (<app_label>_<model>, e.g. hr_department, mail_emailaccount)       │
│   PgBouncer :6432 kept for host tooling only, not live traffic       │
│ Redis :6379  (cache, Celery broker/results, SSE pub/sub bridge)      │
│ Loki :3100, Grafana :3001, Prometheus :9090                          │
└──────────────────────────────────────────────────────────────────────┘
```

Domains are Django apps under `backend/apps/`: `users`, `hr`, `tasks`,
`approvals` (mounted at `/api/requests/`), `cms`, `media_files` (mounted at
`/api/media/`), `mail` (mounted at `/api/email/`), `messenger`, plus `core`
(health checks + the service registry, no domain of its own). Each domain's
URLs live in `apps/<domain>/urls.py` — that is now the source of truth this
document is checked against, not a FastAPI router. See
[STRUCTURE.md](STRUCTURE.md) §3 and [backend/README.md](backend/README.md)
for the app anatomy.

## Access URLs (test stack — `docker compose -f docker-compose.test-local.yml up -d --build`)

The Vite dev server binds `0.0.0.0:3000` with `allowedHosts: true`, so any
of the following work identically over **plain HTTP**:

- `http://localhost:3000`
- `http://127.0.0.1:3000`
- `http://192.168.31.88:3000`         ← LAN
- `http://26.162.180.192:3000`        ← LAN/VPN

> ⚠️ **If you see `ERR_SSL_PROTOCOL_ERROR`** on those URLs, your browser
> cached an HSTS entry from a previous TLS-enabled run of Vite and is now
> forcing `https://`. Vite cannot un-set HSTS over plain HTTP — clear it
> manually:
> 1. `chrome://net-internals/#hsts` → **Delete domain security policies**
>    → enter each affected hostname (`localhost`, `127.0.0.1`,
>    `192.168.31.88`, `26.162.180.192`) → **Delete**.
> 2. Or open in Incognito (HSTS isn't applied there) → confirm HTTP works.
> 3. Then go back to the regular tab and reload — HTTP should stick.

> ⚠️ **`{"detail":"Not Found"}`** typically means the request is missing its
> domain prefix. Use the routing table below — every canonical prefix is
> `/api/<domain>/v1/...`, and it now always resolves to the same backend.

The backend's own ports are also reachable directly in dev (both published
by `docker-compose.yml`): `:8000` (WSGI — `backend-web`), `:8001` (ASGI —
`backend-asgi`). Vite's proxy only forwards `/api/*` and `/ws/*` — hitting
`/health/` bare (not under `/api/`) against `:3000` will 404 from Vite
itself; hit `:8000`/`:8001` directly for that, or use the gateway-level
`/health` (nginx, prod) described below.

## Production access (nginx :80)

`docker compose up -d` (without `-f docker-compose.dev.yml`, and note the
`production` compose profile that adds `nginx`/`certbot`) brings up nginx on
`:80`. Same routing table, but the Vite dev server isn't running. `sfu` и
`webtransport` профиля не требуют — они поднимаются вместе с остальным
стеком в обоих режимах.

---

## Routing table

Source of truth: [infra/nginx/default.conf](infra/nginx/default.conf) (two
upstreams — `backend` for WSGI, `backend_asgi` for ASGI — plus
longest-match `location` blocks). In dev, `frontend/vite.config.ts` mirrors
the same split via one `VITE_BACKEND_TARGET` (WSGI) +
`VITE_MESSENGER_WS_TARGET` (ASGI); the per-domain `*ServiceTarget` variable
names in that file are historical — every one of them now points at the
same backend.

| Prefix                              | Backed by         | Notes                                        |
|-------------------------------------|--------------------|-----------------------------------------------|
| `/`, `/login`, `/register`, `/admin/users`, `/admin/chats`, … | Frontend SPA  | All other paths fall through to React Router |
| `/api/requests/v1/stream`           | `backend_asgi`     | SSE, exact match, unbuffered, 3600s timeout — **before** the general `/api/` rule |
| `/api/hr/v1/public/`                | `backend` (WSGI)   | Public org-chart-by-token, strict rate limit, no auth |
| `/api/email/v1/webhooks/`           | `backend` (WSGI)   | Gmail Pub/Sub + Graph + Mailcow push — **no** rate limit |
| `/api/media/v1/files/` (POST)       | `backend` (WSGI)   | Upload — hard size/rate limit, buffering off |
| `/api/media/`                       | `backend` (WSGI)   | Read/metadata + edge cache of public variants |
| `/api/users/v1/*`                   | `backend` (WSGI)   | Auth, profile, registrations, items, admin   |
| `/api/hr/v1/*`                      | `backend` (WSGI)   | Employees, departments, vacancies, time      |
| `/api/tasks/v1/*`                   | `backend` (WSGI)   | Tasks, calendar, sequences, attachments      |
| `/api/requests/v1/*`                | `backend` (WSGI)   | Approvals: forms, instances, projects, stats, reference sources |
| `/api/messenger/v1/*`               | `backend` (WSGI)   | Rooms, messages, keys (E2EE), attachments    |
| `/api/email/v1/*`                   | `backend` (WSGI)   | OAuth (Google/Microsoft), Mailcow, mailboxes |
| `/api/cms/v1/*`                     | `backend` (WSGI)   | News, categories/tags, contact-requests, ConferenceConfig |
| `/api/contracts/v1/*`               | `backend` (WSGI)   | Budgets, counterparty registry, agreements   |
| `/api/signoff/v1/*`                 | `backend` (WSGI)   | Approval routes + running approvals — **not** `apps.approvals` (`/api/requests/v1`) |
| `/ws/`                              | `backend_asgi`     | Messenger Socket.IO, mounted at `ws/messenger/socket.io` |
| `/ws/sfu/`                          | `sfu` (mediasoup)  | WebRTC signalling for `/conference` — not Django. JWT обязателен: подпротокол `htqweb.jwt`, `Authorization: Bearer` или `?token=` (иначе 401 на upgrade) |
| `:4433/udp` (в обход nginx)         | `webtransport`     | QUIC-сигналинг того же SFU: браузер ходит прямо на UDP-порт, nginx его не проксирует. Токен — в `?token=` |
| `/django-admin/`                    | `backend` (WSGI)   | Django's own admin, session-authenticated (see Authentication) |
| `/static/`                          | `backend` (WSGI)   | `collectstatic` output |
| `/grafana/`, `/prometheus/`         | grafana / prometheus | Observability — see below |

`/sqladmin/*` and `/mongo-admin` are **gone** — there is no nginx location
for either anymore (the old sqladmin aggregator and AdminJS panel were
deleted with the FastAPI services). Database administration is now
`/django-admin/`.

### Temporary compatibility aliases

Vite dev/preview and nginx rewrite cached old frontend paths to canonical
domain prefixes. Examples:

| Old path | Canonical path |
|----------|----------------|
| `/api/token/*`, `/api/register/*`, `/api/items/*` | `/api/users/v1/...` |
| `/api/v1/profile/*`, `/api/pending-registrations/*` | `/api/users/v1/...` |
| `/api/news/*`, `/api/contact-requests/*`, `/api/v1/contact-requests/*` | `/api/cms/v1/...` |
| `/api/calendar-events/*` | `/api/tasks/v1/calendar/...` |
| `/api/calendar-timeline/*` | `/api/tasks/v1/calendar/timeline/...` |
| `/api/media/v1/{not files}/*` | `/api/media/v1/files/...` |
| `/api/users/*`, `/api/hr/*`, `/api/tasks/*`, `/api/cms/*`, `/api/email/*`, `/api/messenger/*` without `/v1/` | matching `/api/<domain>/v1/...` |

Unknown `/api/*` returns JSON 404. Legacy `/media/*` returns JSON 410.

---

## Authentication

### Issue token (login)

```
POST /api/users/v1/token/
Content-Type: application/json

{ "email": "<email_or_username>", "password": "..." }
→ 200 { "access": "<jwt>", "refresh": "<jwt>", "token_type": "Bearer" }
→ 401 { "detail": "Invalid credentials" }
→ 401 { "detail": "Account is not activated" }   # status != ACTIVE
```

JWT claims (HS256 with `JWT_SECRET`, issuer `htqweb-auth` — unchanged from
the FastAPI generation, even though there's no separate user-service
anymore):
```
{ user_id, username, email, is_staff, is_superuser, is_admin,
  token_type: "access" | "refresh", iat, exp, iss }
```
`is_admin = is_staff OR is_superuser`. `apps.users` (`htqweb/authn/jwt.py`)
both issues and validates every token, in-process, for every app — no
introspection round-trip, no separate identity service.

### Refresh token

```
POST /api/users/v1/token/refresh/
Content-Type: application/json

{ "refresh": "<jwt>" }
→ 200 { "access": "<jwt>", "token_type": "Bearer" }
```

### Admin-session cookie — legacy, kept for contract parity, no live consumer

```
POST /api/users/v1/admin-session/login
Content-Type: application/x-www-form-urlencoded

username=admin&password=...&next=/sqladmin/
→ 303 Set-Cookie: admin_session=<jwt>; HttpOnly; SameSite=Lax; Path=/
       Location: /sqladmin/
POST /api/users/v1/admin-session/logout   →   { "ok": true } + clears cookie
```
This pair still exists (`apps/users/views.py::admin_login`/`admin_logout`,
ported byte-for-byte) and `htqweb.http.api_view` still accepts
`auth="admin_session"` for a route that wants it — but **its original
consumer, sqladmin, is gone**, and its default `next` still points at the
now-nonexistent `/sqladmin/`. `/django-admin/` (Django's built-in admin)
does **not** use this cookie; it authenticates with Django's own
session/login form against the same `User` model. Don't wire new code to
`admin_session` expecting it to gate `/django-admin/` — it doesn't.

### Bootstrap an admin user

The `backend-web` process seeds one automatically and idempotently on every
start (`RUN_MIGRATIONS=1` → `docker-entrypoint.sh` → `migrate` then a
`manage.py shell` one-liner):
```
username=admin, password=admin12345, is_staff=is_superuser=True, status=ACTIVE
```
To create another admin by hand:
```bash
docker compose exec backend-web python manage.py createsuperuser
# or, to promote an existing user without Django's interactive prompt,
# use /api/users/v1/admin/users/{id}/ (PATCH, admin only) from an existing admin session.
```

---

## `apps.users` — `/api/users/v1`

### Profile

```
GET  /api/users/v1/profile/me        → ProfileResponse
GET  /api/users/v1/profile/          → ProfileResponse (alias)
PATCH /api/users/v1/profile/me       multipart/form-data → ProfileResponse
PATCH /api/users/v1/profile/         multipart/form-data → ProfileResponse
POST /api/users/v1/profile/change-password  { current_password?, new_password }
DELETE /api/users/v1/profile/avatar          → removes the current avatar
```
PATCH body fields: `display_name`, `firstName`/`first_name`, `lastName`/
`last_name`, `patronymic`, `bio`, `phone`, `settings` (JSON string), and
optional `avatar` (UploadFile — stored via `apps.media_files.interface`,
not forwarded over HTTP to a separate media service anymore).

### Registration

```
POST /api/users/v1/register/                          { email, password, full_name }
GET  /api/users/v1/pending-registrations/             admin only
POST /api/users/v1/pending-registrations/{id}/approve/  → 204
POST /api/users/v1/pending-registrations/{id}/reject/   → 204
```

### Admin user management

```
GET  /api/users/v1/admin/users/                       admin only
PATCH /api/users/v1/admin/users/{id}/                 admin only
POST /api/users/v1/admin/users/{id}/set-password/     admin only
```

### Items (personal notes)

```
GET    /api/users/v1/items/
POST   /api/users/v1/items/                           { title, description }
GET    /api/users/v1/items/{id}/          (no bare-slash alias — not called that way by the frontend)
PATCH  /api/users/v1/items/{id}/
DELETE /api/users/v1/items/{id}/
```

### Options / picker

```
GET /api/users/v1/users/options/       any authenticated user — used by other domains' "assign to user" pickers
```

### Client-side error/event ingestion

```
POST /api/users/v1/client-errors/                     { message, stack, url, user_agent, ... }
POST /api/users/v1/client-events/                     { event, payload, ... }
```

---

## `apps.hr` — `/api/hr/v1`

| Endpoint                                  | Method | Notes                          |
|-------------------------------------------|--------|---------------------------------|
| `/api/hr/v1/employees/`                   | GET, POST | Employee CRUD. Тело POST/PUT принимает опциональный `card_t2: {financial?, personal?, certs?}` — секции Т-2 пишутся в той же транзакции, посекционный RBAC `hr.card.<section>.edit` |
| `/api/hr/v1/employees/{id}/`              | GET, PATCH, DELETE |                       |
| `/api/hr/v1/employees/me`                 | GET    | Current user's own employee row |
| `/api/hr/v1/employees/me/card`            | GET    | Т-2 employee card (field-gated) |
| `/api/hr/v1/employees/users/`             | GET, POST | User picker for "create employee from user"; POST creates the platform user via `apps.users.interface.create_user` |
| `/api/hr/v1/departments/`                 | GET, POST | Tree (`ltree path`)         |
| `/api/hr/v1/departments/tree`             | GET    | Full tree                      |
| `/api/hr/v1/positions/`                   | GET, POST |                              |
| `/api/hr/v1/positions/levels/`            | GET, POST | Level thresholds                |
| `/api/hr/v1/vacancies/`                   | GET, POST |                              |
| `/api/hr/v1/applications/`                | GET, POST | Candidate applications      |
| `/api/hr/v1/time/`                        | GET, POST | Time tracking               |
| `/api/hr/v1/documents/`                   | GET, POST | HR documents (now plain Django models, MongoDB is gone) |
| `/api/hr/v1/department-folders/`          | GET    | Department folders visible to current user |
| `/api/hr/v1/department-file-folders/`     | GET, POST | User-created folders inside a department |
| `/api/hr/v1/department-files/`            | GET, POST | Department-scoped files; stored via `apps.media_files.interface` |
| `/api/hr/v1/department-files/{id}/`       | DELETE | Remove HR metadata for a department file |
| `/api/hr/v1/audit/`                       | GET    | Read-only audit log            |
| `/api/hr/v1/org/`                         | GET    | Organisational settings        |
| `/api/hr/v1/pmo/`                         | GET, POST | Project management office   |
| `/api/hr/v1/share-links/`                 | GET, POST |                              |
| `/api/hr/v1/public/org/{token}`           | GET    | Public org-chart by share link — nginx `api_public` rate limit |

Source: `backend/apps/hr/urls.py` (170 registered patterns, counting both
slash spellings — see [STRUCTURE.md §4.2](STRUCTURE.md) for HR-adjacent
detail and [backend/apps/hr/services/](backend/apps/hr/services/) for the
business logic).

---

## `apps.tasks` — `/api/tasks/v1`

| Endpoint                                          | Method | Notes                       |
|---------------------------------------------------|--------|-----------------------------|
| `/api/tasks/v1/tasks/`                            | GET, POST | List + create            |
| `/api/tasks/v1/tasks/{id}/`                       | GET, PATCH, DELETE |                  |
| `/api/tasks/v1/tasks/{id}/comments/`              | GET, POST |                           |
| `/api/tasks/v1/tasks/{id}/attachments/`           | GET, POST |                           |
| `/api/tasks/v1/tasks/{id}/activity/`              | GET    | Activity log                 |
| `/api/tasks/v1/tasks/{id}/links/`                 | GET, POST | Cross-task links          |
| `/api/tasks/v1/tasks/{id}/supervisor/`            | PATCH  | `{user_id\|null}`             |
| `/api/tasks/v1/tasks/{id}/assignees/`             | PATCH  | `[{user_id, role}]`           |
| `/api/tasks/v1/tasks/{id}/delegates/`             | POST   | `{user_id}` — supervisor only |
| `/api/tasks/v1/tasks/{id}/delegates/{user_id}/`   | DELETE |                               |
| `/api/tasks/v1/tasks/{id}/watch/`                 | POST, DELETE |                         |
| `/api/tasks/v1/tasks/{id}/progress/`              | PATCH  | `{percent}`                   |
| `/api/tasks/v1/labels/`                           | GET, POST |                           |
| `/api/tasks/v1/versions/`                         | GET, POST | Project versions          |
| `/api/tasks/v1/projects/`                         | GET, POST |                            |
| `/api/tasks/v1/projects/{id}/`                    | GET, PATCH, DELETE |                  |
| `/api/tasks/v1/projects/{id}/tasks/`              | GET    |                              |
| `/api/tasks/v1/roadmaps/`                         | GET, POST | Пакеты работ **на блоке**: проект → площадка → блок → **роудмап** → задача. Тело принимает `site_block_id`; площадки колонкой нет, `?site_id=` фильтрует джойном |
| `/api/tasks/v1/roadmaps/{id}/`                    | GET, PATCH, DELETE | Правка — владелец или админ. DELETE непустого пакета → 409 |
| `/api/tasks/v1/roadmaps/{id}/tasks/`              | GET    |                              |
| `/api/tasks/v1/roadmaps/{id}/metrics/`            | GET    | План (руками) против факта (свёрнут из задач): срок, люди, техника |
| `/api/tasks/v1/sites/{id}/blocks/`                | GET, POST | Блоки объекта: «Сазаган → блок 1, блок 2» |
| `/api/tasks/v1/blocks/{id}/`                      | GET, PATCH, DELETE | 409, если на блок ссылаются задачи |
| `/api/tasks/v1/blocks/{id}/volumes/`              | GET, PUT | Плановые объёмы; PUT заменяет набор целиком |
| `/api/tasks/v1/blocks/{id}/progress/`             | GET    | Выполнение **в штуках**, не в статусах задач |
| `/api/tasks/v1/tasks/{id}/volumes/`               | GET, PUT | ПЛАНОВЫЕ объёмы задачи. Факт в ответе есть, но это свёртка отчётов, а не поле |
| `/api/tasks/v1/tasks/{id}/daily-reports/`         | GET, POST | Ежедневный отчёт: сколько сделано и **когда** (`work_date` — дата ВЫПОЛНЕНИЯ, не заполнения). Единственный источник факта |
| `/api/tasks/v1/daily-reports/{id}/`               | GET, PATCH, DELETE | PATCH поднимает `current_revision` и пишет снимок; DELETE мягкий |
| `/api/tasks/v1/daily-reports/{id}/revisions/`     | GET    | Лента версий отчёта — «аналог Git» |
| `/api/tasks/v1/roadmaps/{id}/daily-reports/`      | GET    | Отчёты всего пакета; `?date_from=&date_to=` |
| `/api/tasks/v1/plan-fact/project/{id}/`           | GET    | Дерево проект → площадки → блоки → роудмапы: SPI, прогноз, отставание, S-кривая. `?date=` — отчётная дата |
| `/api/tasks/v1/plan-fact/roadmap/{id}/`           | GET    | То же + задачи пакета и его серии по дням |
| `/api/tasks/v1/equipment-usage/`                  | GET    | Что задействовано на дату D + история интервалов. Узел задаётся ровно одним из `project_id`/`site_id`/`block_id`/`roadmap_id`/`task_id` |
| `/api/tasks/v1/resource-requirements/`            | GET, POST | План количеством: «2 человека», «2 кары». `task_id` XOR `roadmap_id` |
| `/api/tasks/v1/resource-requirements/{id}/`       | PATCH, DELETE |                       |
| `/api/tasks/v1/assignments/`                      | GET, POST | Факт именами. `task_id` XOR `roadmap_id` |
| `/api/tasks/v1/assignments/{id}`                  | DELETE |                              |
| `/api/tasks/v1/task-types/`                       | GET, POST | User-extensible registry  |
| `/api/tasks/v1/task-types/{id}/`                  | GET, PATCH, DELETE |                  |
| `/api/tasks/v1/equipment-categories/`             | GET, POST | Типы техники: «кара (вилопогрузчик)». Запись — админ |
| `/api/tasks/v1/work-roles/`                       | GET, POST | Роли в потребности: «монтажник» |
| `/api/tasks/v1/volume-types/`                     | GET, POST | Виды объёмов: «валы» + единица измерения |
| `/api/tasks/v1/calendar/`                         | GET, POST | Calendar events           |
| `/api/tasks/v1/calendar/{id}/`                    | PATCH, DELETE | Calendar event         |
| `/api/tasks/v1/calendar/{id}/exceptions/`         | POST   | Calendar event exception      |
| `/api/tasks/v1/calendar/timeline/`                | GET    | `{ tasks, events }` by `start`/`end` |
| `/api/tasks/v1/production-calendar/`              | GET, PATCH | Production days, Kazakhstan holidays |
| `/api/tasks/v1/sequences/`                        | GET    | Jira-style key generators     |
| `/api/tasks/v1/notifications/`                    | GET    |                              |

Source: `backend/apps/tasks/urls.py`. FSM transitions and the role model
(reporter/supervisor/assignee/delegate/watcher) are unchanged from the
FastAPI original — see [STRUCTURE.md §4.2](STRUCTURE.md).

---

## `apps.approvals` — `/api/requests/v1` (+ SSE)

Mounted at `/api/requests/`, even though the Django app label is
`approvals` (`ApprovalsConfig.API_PREFIX = "api/requests/v1/"` —
deliberate, see `apps/approvals/urls.py`'s docstring).

| Endpoint                                                   | Method | Notes |
|-------------------------------------------------------------|--------|-------|
| `/api/requests/v1/instances/`                               | GET, POST |     |
| `/api/requests/v1/instances/batch-approve`                  | POST   | Registered before the `<id>` routes |
| `/api/requests/v1/instances/{id}/`                          | GET, PATCH | PATCH only while still a draft |
| `/api/requests/v1/instances/{id}/submit/` … `/resubmit/`, `/approve/`, `/reject/`, `/request-changes/`, `/cancel/`, `/recall/` | POST | Workflow actions |
| `/api/requests/v1/templates/`                                | GET, POST | Form templates |
| `/api/requests/v1/templates/{id}/`                            | GET, PATCH, DELETE |     |
| `/api/requests/v1/templates/{id}/versions/`                   | POST   | Publish a version |
| `/api/requests/v1/templates/{id}/versions/{version_id}`        | GET    | Read a version |
| `/api/requests/v1/templates/{id}/activate/` / `/deactivate/`  | POST   |     |
| `/api/requests/v1/templates/preview`                          | POST   | Registered before `{id}` routes |
| `/api/requests/v1/projects/`                                  | GET, POST |     |
| `/api/requests/v1/projects/{id}/`                              | GET, PATCH, DELETE |     |
| `/api/requests/v1/projects/{id}/members/`                      | GET, POST |     |
| `/api/requests/v1/projects/{id}/members/{user_id}/`             | DELETE |     |
| `/api/requests/v1/reference-sources/`                          | GET, POST | Lark-Base-style lookup tables |
| `/api/requests/v1/reference-sources/{id}/`                      | GET, PATCH, DELETE |     |
| `/api/requests/v1/reference-sources/{id}/access`                | PATCH  |     |
| `/api/requests/v1/reference-sources/{id}/rows/`                 | GET, POST |     |
| `/api/requests/v1/reference-sources/{id}/rows/{row_id}`          | DELETE |     |
| `/api/requests/v1/reference-sources/my-data-tables`              | GET    |     |
| `/api/requests/v1/reference-sources/by-slug/{slug}/options`      | GET    |     |
| `/api/requests/v1/stats/{overview,by-project,by-template,by-actor,heatmap}` | GET |  |
| `/api/requests/v1/stream`                                      | GET    | SSE, see below |

### SSE — `GET /api/requests/v1/stream`

Served by the **ASGI** process (`backend-asgi`), not WSGI — nginx routes
this one path to the `backend_asgi` upstream with buffering off and a
3600s timeout (see the routing table above). Cross-process bridge: an
action performed against `backend-web` (WSGI) publishes to a Redis
pub/sub channel (`apps/approvals/services/dispatch.py::publish_sse`);
`backend-asgi`'s open SSE connection subscribes and forwards
(`apps/approvals/services/sse.py`). This is the one place Redis pub/sub is
still load-bearing in the new architecture (see "Internal conventions"
below).

---

## `apps.messenger` — `/api/messenger/v1` + Socket.IO

### REST

| Endpoint                                                | Method | Notes                            |
|-----------------------------------------------------------|--------|----------------------------------|
| `/api/messenger/v1/rooms/`                              | GET, POST | Create/list rooms             |
| `/api/messenger/v1/rooms/{id}`                          | GET, PATCH |                               |
| `/api/messenger/v1/messages/`                           | POST   | Send message → emits `message_new` |
| `/api/messenger/v1/messages/room/{id}`                  | GET    | Paginated history                 |
| `/api/messenger/v1/messages/room/{id}/read/{msg_id}`    | POST   | → emits `message_read`            |
| `/api/messenger/v1/messages/room/{id}/typing`           | POST   | → emits `user_typing` (frontend actually uses the Socket.IO `typing` event instead, see below) |
| `/api/messenger/v1/keys/`                               | POST   | Upload E2EE pre-key bundle       |
| `/api/messenger/v1/keys/{user_id}`                      | GET    | Fetch peer's pre-keys             |
| `/api/messenger/v1/attachments/upload`                  | POST   | Multipart upload                  |
| `/api/messenger/v1/attachments/file/{id}`               | GET    | Serve attachment                  |
| `/api/messenger/v1/attachments/file/{id}/thumb`         | GET    | Serve attachment thumbnail        |
| `/api/messenger/v1/users/ingest`                        | POST   | Replicate/upsert a user replica row |
| `/api/messenger/v1/users/me`                            | GET    | Current user's messenger identity |
| `/api/messenger/v1/users/search`                        | GET    | User picker for starting a chat  |
| `/api/messenger/v1/internal/bot-message`                | POST   | Internal/bot-only, `X-Internal-Token` header (not JWT) |
| `/api/messenger/v1/admin/rooms`                         | GET    | Admin: all rooms                 |
| `/api/messenger/v1/admin/rooms/{id}/messages`           | GET    | Admin: full history               |
| `/api/messenger/v1/admin/history/archive`               | POST   | Admin: trigger the weekly history archive job |

### Socket.IO

```
URL:  ws://<host>:3000/ws/messenger/socket.io/     (dev, via Vite)
      ws://<host>/ws/messenger/socket.io/           (prod, via nginx → backend_asgi)
Auth: { token: "<JWT>" }   (also accepted as ?token=… or Authorization: Bearer …)
```
Served by the ASGI process (`backend-asgi`) — `python-socketio`'s
`ASGIApp` wraps Django's ASGI app in `htqweb/asgi.py`; handlers live in
`apps/messenger/socket.py`. The `connect` handler itself calls
`require_service("messenger")` (`ServiceGateMiddleware` doesn't cover the
WebSocket scope, so the app checks its own gate here).

**Server → Client events:**

| Event           | Payload                                                      |
|-----------------|----------------------------------------------------------------|
| `message_new`   | `{ room_id, message: {...} }`                                |
| `message_read`  | `{ room_id, message_id, reader_user_id }`                    |
| `user_typing`   | `{ room_id, user_id, is_typing }`                             |

**Client → Server events:**

| Event       | Payload                       | ack                                         |
|-------------|--------------------------------|-----------------------------------------------|
| `join_room` | `{ room_id }`                 | `{ ok: true }` or `{ ok: false, error: "not_a_member" }` |
| `leave_room`| `{ room_id }`                 | `{ ok: true }`                                |
| `typing`    | `{ room_id, is_typing }`      | —                                              |
| `mark_read` | `{ room_id, message_id }`     | — (also persists `last_read_message_id`)      |

---

## `apps.media_files` — `/api/media/v1`

| Endpoint                            | Method | Notes                                   |
|--------------------------------------|--------|-------------------------------------------|
| `/api/media/v1/files/`              | GET, POST | GET lists (admin only); POST uploads → `FileMetadataRead` |
| `/api/media/v1/files/{id}/sign`     | POST   | Issue a signed URL for a private file |
| `/api/media/v1/files/{id}/{variant}`| GET    | Download a variant (Range, ETag support) |
| `/api/media/v1/files/{path:path}`   | GET    | Raw storage-key fallback — files with no `FileMetadata` row (avatars) |

This app is the **shared file domain** now — `hr` (department files),
`mail` (attachment seam), `messenger` (attachments), and `users`
(avatars) all store through `apps.media_files.interface`
(`store_file`/`get_file_url`/`delete_file`) instead of each keeping its own
storage client. `cms` is the one exception; it kept its own bucket and
calls `htqweb.storage` directly (it predates `media_files` as an app). See
[STRUCTURE.md §7.1](STRUCTURE.md).

---

## `apps.mail` — `/api/email/v1`

Grew considerably during the port relative to the old `email-service`
surface — this table reflects `backend/apps/mail/urls.py` as it stands now,
not the FastAPI original.

| Endpoint                                            | Method | Notes                            |
|-------------------------------------------------------|--------|-----------------------------------|
| `/api/email/v1/accounts/`                            | GET    | List mail accounts (corporate + personal) — connecting one happens via `oauth/connect/{provider}` or mailbox provisioning, not a direct POST here |
| `/api/email/v1/accounts/{id}/`                       | DELETE | Disconnect a personal account (corporate mailboxes go through `/mailboxes/{id}/archive/` instead) |
| `/api/email/v1/accounts/{id}/set-default/`           | POST   |                                    |
| `/api/email/v1/accounts/{id}/sync/`                  | POST   | Trigger an incremental sync        |
| `/api/email/v1/folder/{folder}`                      | GET    | List messages in a folder (inbox/sent/drafts/trash/outbox) |
| `/api/email/v1/unread-counts/`                       | GET    |                                    |
| `/api/email/v1/send`                                 | POST   | `folder='outbox'` + `deliver_email.delay(...)` (Celery) |
| `/api/email/v1/draft`                                | POST   | Save a draft                       |
| `/api/email/v1/{message_id}`                         | GET    |                                    |
| `/api/email/v1/{message_id}/read`                    | POST   | Mark as read                       |
| `/api/email/v1/oauth/status`                         | GET    |                                    |
| `/api/email/v1/oauth/accounts`                       | GET    |                                    |
| `/api/email/v1/oauth/connect/{provider}`             | POST   | `provider` = `google`\|`microsoft` — returns the provider's consent URL |
| `/api/email/v1/oauth/callback`                       | GET    | `auth=None` — the provider redirects the browser here directly |
| `/api/email/v1/oauth/disconnect`                     | DELETE | Disconnects all of the caller's OAuth accounts |
| `/api/email/v1/mailboxes/`                           | GET, POST | Corporate mailbox provisioning (admin). POST really creates the mailbox on the mail server; `502` + `{detail, mailbox}` when the server refuses (the local row survives, flagged `status=error`) |
| `/api/email/v1/mailboxes/status/`                    | GET    | What the connected mail server can do — `provisioner` (`mailcow`\|`imap`\|`none`), `domain`, `can_create_remotely`, `can_list_remote`, `allow_self_service`. The admin UI reads it to avoid promising what the server can't do |
| `/api/email/v1/mailboxes/settings/`                  | GET, PUT | Mail-server credentials, editable from the UI. Response splits `value` (stored in the DB; empty = inherit) from `effective` (what actually applies), plus `overridden` listing which fields the DB wins. The Mailcow API key is write-only — `mailcow_api_key_set` is the only thing read back; `""` means "leave unchanged", `null` clears the override |
| `/api/email/v1/mailboxes/settings/test/`             | POST   | Runs the same check chain as `manage.py mail_check` and returns it as `{ok, steps[]}` — each step carries `status` (`ok`\|`fail`\|`skip`), `detail`, an actionable `hint`, and `data` (e.g. the server's real folder list). Passwords are never echoed back |
| `/api/email/v1/accounts/connect-imap/`               | GET, POST | **Non-admin.** Connect any mailbox over IMAP/SMTP — the third way to add mail, next to OAuth and the corporate mailbox. GET (`?address=`) returns suggested server settings (known providers verbatim, otherwise `imap.<domain>` flagged `guessed`); POST verifies the credentials with a live IMAP login **before** writing anything. No domain restriction — this is the user's own mailbox, not a platform resource |
| `/api/email/v1/accounts/{id}/imap-password/`         | POST   | **Non-admin.** Update the stored password after changing it on the server; the new one is verified by logging in, so sync cannot silently stall |
| `/api/email/v1/accounts/connect-corporate/`          | GET, POST, DELETE | **Non-admin.** Self-service: an employee connects their own corporate mailbox (`{address, password}` verified by a live IMAP login before anything is written). GET reports `allowed`/`domain`/current mailbox; DELETE detaches it from the platform without touching the mail server. Requires `allow_self_service`; the address domain must match the corporate one, and a mailbox already owned by someone else is a `409` |
| `/api/email/v1/mailboxes/reconcile/`                 | GET, POST | Two-way platform ↔ mail-server reconciliation. GET = report only. POST body `{apply, direction}`, `direction` = `report`\|`pull`\|`push`\|`both` |
| `/api/email/v1/mailboxes/{id}/`                      | GET, PATCH |                                 |
| `/api/email/v1/mailboxes/{id}/reset-password/`       | POST   | `502` when the mail server rejects the change — the stored password is left untouched |
| `/api/email/v1/mailboxes/{id}/archive/` / `/restore/`| POST   | Also disables/enables the mailbox on the server |
| `/api/email/v1/mailboxes/{id}/forwarding/`           | POST   | Mailcow only                       |
| `/api/email/v1/mailboxes/aliases/`                   | GET, POST | Mailcow only                    |
| `/api/email/v1/mailboxes/aliases/{id}/`              | DELETE | Mailcow only                       |
| `/api/email/v1/webhooks/gmail`                       | POST   | Public, no rate limit — Gmail Pub/Sub, Bearer JWT verified in-app |
| `/api/email/v1/webhooks/microsoft`                   | POST   | Public, no rate limit — Graph subscriptions (`validationToken` echo) |
| `/api/email/v1/webhooks/mailcow`                     | POST   | Public, no rate limit |

**Attachments are metadata-only** — `EmailAttachment` rows exist, but no
route on this list accepts attachment bytes (true of the FastAPI original
too, not a migration regression). `apps/mail/services/attachment_service.py`
has a `store_attachment` seam ready (via `apps.media_files.interface`,
scope `generic`) for whenever that's wired up.

Sync engine (`apps/mail/services/sync/`), send strategy
(`apps/mail/services/sender/`), OAuth-token encryption
(`apps/mail/services/crypto.py`, AES-256-GCM) and the mailbox-archive/purge
Celery beat job (`final_purge_archived_mailboxes`, cron 03:15) are ported
from `services/email` — see [STRUCTURE.md §4.1](STRUCTURE.md) for the deep
dive.

### Corporate mail server

**Where the settings live.** `apps/mail/services/mail_config.py` is the single
resolver every consumer reads: it merges the `MailServerConfig` row (edited in
the UI, `/admin/mailboxes` → «Подключение») **over** the env defaults, with one
rule — *an empty field in the DB means "take it from env"*. So an environment
that never touched the UI behaves exactly as before, env stays valid for the
initial rollout, and clearing a field in the form reverts it. Booleans in the
DB are nullable precisely so `imap_ssl=false` can override `IMAP_SSL=true`
(a plain boolean could not tell "off" from "unset"). Only the DB read is
cached (5s); the merge runs per call, so `override_settings` keeps working.

Which server the platform talks to is a runtime setting, not a code branch —
`MAIL_PROVISIONER` (`auto`\|`mailcow`\|`imap`\|`none`), resolved by
`apps/mail/services/provisioning/factory.py`:

* **`mailcow`** — Mailcow REST API (`MAILCOW_API_URL` + `MAILCOW_API_KEY`).
  Creates, edits, disables and deletes mailboxes for real, and can list every
  mailbox of the domain, so reconciliation sees both sides.
* **`imap`** — a plain IMAP/SMTP server with no admin API (`IMAP_HOST`).
  IMAP has no "create mailbox" command, so creating from the site means
  *verify the credentials with a live IMAP login and link the existing
  mailbox*; reconciliation falls back to probing each known row
  (`mode: "probe"` in the report — server-only mailboxes are undetectable
  there by construction, and the report says so).
* **`none`** (default when nothing is configured) — local row only, exactly
  the pre-existing behaviour.

Messages sync both ways for corporate accounts
(`apps/mail/services/sync/imap_sync.py`): new mail is pulled per folder using
a `UIDVALIDITY`-checked UID cursor kept in `EmailAccount.sync_state`, and
messages read in the platform are pushed back as `\Seen`
(`MAIL_SYNC_PUSH_FLAGS`). The driver runs from `incremental_sync_account`,
enqueued every 60s by `imap_poll_fallback` — for a non-Mailcow server that
poll is the only source of new mail, since there are no webhooks.

When the mail server is only reachable over SSH, the `mail-tunnel` compose
profile (`infra/mail-tunnel/`) forwards IMAP and SMTP; point `IMAP_HOST`/
`SMTP_HOST` at it. Setup is in `.env.example`.

---

## `apps.cms` — `/api/cms/v1`

| Endpoint                                       | Method | Notes                              |
|---------------------------------------------------|--------|----------------------------------|
| `/api/cms/v1/news/`                              | GET, POST | Public list + admin create     |
| `/api/cms/v1/news/{id}`                          | GET, PATCH, DELETE |                          |
| `/api/cms/v1/news/by-slug/{slug}`                | GET    |                                    |
| `/api/cms/v1/categories/`                        | GET, POST |                                 |
| `/api/cms/v1/categories/{id}`                    | PATCH, DELETE | admin only, no single-item GET |
| `/api/cms/v1/tags/`                              | GET, POST |                                 |
| `/api/cms/v1/tags/{id}`                          | PATCH, DELETE | admin only, no single-item GET |
| `/api/cms/v1/contact-requests/`                  | POST   | **Public**, rate-limited          |
| `/api/cms/v1/contact-requests/`                  | GET    | Admin queue                       |
| `/api/cms/v1/contact-requests/stats`             | GET    | `{ total, unread, ... }`          |
| `/api/cms/v1/contact-requests/{id}`              | GET, PATCH, DELETE |                          |
| `/api/cms/v1/contact-requests/{id}/reply`        | POST   |                                    |
| `/api/cms/v1/conference/config`                  | GET    | Static SFU/ICE config (no DB) — `apps.cms.services.conference_service` |

`conference/config` отдаёт: `sfu_signaling_url` (пустой = фронт берёт
`ws(s)://<origin>/ws/sfu/`), `sfu_signaling_path`, `ice_servers`, `enabled`
(флаг сервиса `conference` в реестре) и пару полей QUIC-сигналинга —
`wt_signaling_url` (адрес моста `webtransport`, пустой = мост не
анонсирован, работаем по WebSocket) и `wt_certificate_hashes` (DER SHA-256
самоподписанного сертификата моста для dev; с сертификатом от настоящего CA
список пуст).

---

## `apps.contracts` — `/api/contracts/v1`

Budgets, the counterparty registry, and agreements.

**Permissions are no longer a flat "read = JWT, write = admin".** Since
`apps.signoff` was wired in, approval — not the admin flag — is the control
on the three approvable models:

| Operation | Auth |
|-----------|------|
| All reads | any valid JWT |
| **Create** a budget / counterparty / agreement (incl. the `/full` variants) | any valid JWT |
| **Submit** one for approval (`/submit`) | any valid JWT |
| **Attach a scan** (`agreements/{id}/file`) | author while the agreement is `draft`, or admin always — checked on the row, not by decorator |
| Everything else — PATCH, DELETE, `/status`, and the whole reference layer (countries, programs, administrators) | admin |

The rationale: if only an admin can create a budget line, a three-stage
approval route over budget lines has nothing to approve. Attaching the scan
is bundled with creation because an agreement without its document isn't
worth submitting; replacing it after submission stays admin-only, since
`attach_file` **replaces** the reference and swapping the scan mid-approval
would mean approvers signed off on a document that is no longer in the card.

Every path is registered in **both** the slashed and bare spelling
(`APPEND_SLASH = False`). No frontend consumes this yet.

| Endpoint                                          | Method | Notes                          |
|---------------------------------------------------|--------|--------------------------------|
| `/api/contracts/v1/enums`                        | GET    | Choice labels + `committing_statuses` + status-transition table, so the frontend doesn't keep its own copy |
| `/api/contracts/v1/countries`                    | GET, POST | Reference                   |
| `/api/contracts/v1/countries/{id}`               | GET, PATCH, DELETE |                    |
| `/api/contracts/v1/programs`                     | GET, POST | «Программа» + «Статья расходов» in one row. Reads carry `display_name` (`"<code> <name>"`, name alone when the optional code is empty) — the same string budget/agreement cards return as `program_name`; `?is_active=` |
| `/api/contracts/v1/programs/{id}`                | GET, PATCH, DELETE |                    |
| `/api/contracts/v1/administrators`               | GET, POST | «Администратор бюджета» — a **project in a country** (no person's name, holds no money). Reads carry `country_name` + `display_name` (`"<project> <country>"`); `?is_active=&country_id=` |
| `/api/contracts/v1/administrators/{id}`          | GET, PATCH, DELETE |                    |
| `/api/contracts/v1/budgets`                      | GET, POST | Budget lines; `?administrator_id=&program_id=&period_year=&status=&approval_state=` |
| `/api/contracts/v1/budgets/full`                 | POST   | Budget + its reference rows in one transaction (the "заявка на бюджет" form) |
| `/api/contracts/v1/budgets/{id}`                 | GET, PATCH, DELETE | Response carries computed `committed`/`remaining` — no such columns exist |
| `/api/contracts/v1/budgets/{id}/agreements`      | GET    | What the budget's remaining is made of |
| `/api/contracts/v1/budgets/{id}/submit`          | POST   | **→ approval.** Returns a signoff process card (201), not the budget |
| `/api/contracts/v1/counterparties`               | GET, POST | «Реестр контрактов»; `vat` is a **boolean** (payer / not — no rate, no certificate number), reads also carry `vat_label` (`"с НДС"`/`"без НДС"`); `?search=` matches name **or** БИН/ИИН; `?approval_state=` |
| `/api/contracts/v1/counterparties/full`          | POST   | Counterparty + country in one transaction |
| `/api/contracts/v1/counterparties/{id}`          | GET, PATCH, DELETE |                    |
| `/api/contracts/v1/counterparties/{id}/submit`   | POST   | **→ approval.** Returns a signoff process card (201) |
| `/api/contracts/v1/agreements`                   | GET, POST | `?budget_id=&counterparty_id=&administrator_id=&program_id=&period_year=&status=` |
| `/api/contracts/v1/agreements/{id}`              | GET, PATCH, DELETE | PATCH ignores `status`; DELETE only for drafts |
| `/api/contracts/v1/agreements/{id}/submit`       | POST   | **→ approval.** Draft only; re-checks currency, references and the budget limit *before* starting, because `on_review` already commits budget |
| `/api/contracts/v1/agreements/{id}/status`       | POST   | Manual status change — validates the transition. Approval drives the same machine automatically |
| `/api/contracts/v1/agreements/{id}/file`         | POST   | multipart, field `file` → stored via `apps.media_files.interface.store_file` |
| `/api/contracts/v1/agreements/{id}/file-url`     | GET    | Signed URL for the stored scan |

### Approval fields and the two axes

All three approvable models now return **`approval_state`** (`draft` /
`pending` / `approved` / `rejected` / `rework`) alongside their existing
`status`. These are **different axes and both stay**: `status` is the
record's own lifecycle (budget closed, counterparty blocked, agreement
terminated), `approval_state` is where it sits in a signoff route. An
agreement can be `approved` by route and `terminated` in substance.

**`approval_state` also decides whether the row can be edited at all.**
Editable: `draft` and `rework`. Locked (409 on any PATCH/DELETE, and on the
child `budget-lines` of a locked budget): `pending`, `approved`, `rejected`
— a document under approval must not change under the approvers, and one
that has been decided must stay the document that was decided. The only key
is **«вернуть на доработку»** — the `rework` decision while the round runs,
or `POST /api/signoff/v1/processes/{id}/rework` once it has closed. A
decided object also cannot be re-submitted (`/submit` → 409); return it for
rework first. If `signoff` is switched off, the lock lifts entirely.

`Agreement` is the only one where approval has a domain consequence — it
drives the existing `status` machine through `ALLOWED_TRANSITIONS`:

```
submit   → draft      → on_review     (and on_review already commits budget)
approve  → on_review  → approved
reject   → on_review  → draft         (status only; the row stays locked)
rework   → on_review  → draft         (locked → editable, resubmit as a new round)
reopen   → approved   → draft         (same, from an already-approved agreement)
cancel   → on_review  → draft
```

### The gate: unapproved things can't be spent or contracted

`agreement_service._validate_context` refuses an unapproved `Budget` as a
funding source and an unapproved `Counterparty` as a party — **but only when
an active route exists for that subject type** (`signoff.has_active_route`).
With no route configured nothing is blocked, because every pre-existing row
is `draft` and an unconditional check would have bricked the module on day
one. Configuring a budget route is therefore a consequential act: from that
moment unapproved budget lines stop being spendable.

The gate fires on create and when the reference is re-pointed, never on an
ordinary edit — otherwise revoking a budget's approval after the fact would
lock you out of fixing a typo in a long-signed agreement.

If `signoff` is disabled (`manage.py service signoff --off`) the gate lifts
rather than failing: contracts keeps working, and only `/submit` returns
503. A disabled approval module should stop *requiring* approval, not stop
the contract registry.

**409 Conflict** is used throughout for "well-formed request, impossible
given the data": duplicate budget line / agreement number / БИН, an amount
that exceeds the budget's remaining, a currency mismatch with the budget
line, a disallowed status transition, a `PROTECT`ed reference still in use,
and — since the signoff wiring — no route configured, the object already
under approval, or an unapproved budget/counterparty. It is deliberately
distinct from the `422` `api_view` returns for schema violations — the
frontend needs to show the message rather than "check your fields".

---

## `apps.signoff` — `/api/signoff/v1`

Generic multi-stage approval. **Do not confuse with `apps.approvals`
(`/api/requests/v1`)** — that one is a form *designer*: it approves
`RequestInstance` rows holding JSON field values it owns. `signoff` approves
rows that already exist in **another app's own table**, addressed by a
`(subject_type, subject_id)` pair — `"contracts.budget"` + a pk. There is no
`ContentType` and no cross-app FK; the domain app hands over its model class
and callbacks at startup (`AppConfig.ready()` → `signoff.register_subject`),
so the dependency only ever points *domain → signoff*.

**Route shape.** A route is an ordered list of stages. Stages with the
**same `order` run in parallel**; different `order` runs sequentially. Each
stage names its approvers explicitly (user ids — the platform has no groups;
`User` deliberately omits `PermissionsMixin`) and a `quorum` of `any` or
`all`. **Any negative decision at any stage closes the whole process
immediately**; outstanding requests are marked `skipped`, not left hanging.
Exactly one active route per subject type (partial unique index).

**Three decisions, and the difference is the subject, not the mechanics.**
`approve` moves the round on; `reject` and `rework` both end it on the spot.
What they do to the approved *object* differs, and that is the whole point:

| decision | process | `approval_state` | object editable? |
|---|---|---|---|
| `approve` (last stage) | `approved` | `approved` | **no** |
| `reject`               | `rejected` | `rejected` | **no** — "this document won't do" |
| `rework`               | `rework`   | `rework`   | **yes** — "fix it and send it back" |
| `cancel` (initiator)   | `cancelled`| `draft`    | yes — not a decision at all |

Editability is enforced by the domain app calling
`Approvable.assert_editable()` first thing in every edit/delete service
(signoff cannot intercept writes to another app's tables — it owns the
column, the table's owner has to guard it), and it raises `SubjectLocked`,
a `SignoffError`, which the domain views already translate to 409. A decided
object is unlocked only by `POST /processes/{id}/rework`; it cannot be
re-submitted while locked either. With `signoff` disabled the lock lifts —
a disabled approval module stops *requiring* approval rather than freezing
everything mid-flight, which matters because unlocking runs through signoff.

**Signature stages.** Two independent stage flags cover "the author signs
last, with the signed PDF attached":

* `approver_kind` — `named` (the default: approvers listed in the route) or
  `initiator`, where the single approver is resolved **at start** from
  `ApprovalProcess.initiator_id`. It is deliberately *initiator*, not
  "creator": signoff cannot read a domain model's `created_by`, and in
  contracts the two are the same person by business process. Such a stage
  must carry **no** `approver_ids` (409/422 otherwise), and its `quorum` is
  meaningless — there is exactly one task.
* `requires_attachment` — the stage can only be **approved** with a PDF
  already attached to the task (`ApprovalTask.file_id`). Rejection needs no
  document: there is nothing for the refuser to sign. Both flags are part of
  the start-time snapshot, so unticking them mid-flight does not release
  approvers who haven't decided yet.

There is no "final stage" concept: a process completes when the highest
`order` group is approved (`engine._advance`). A signature stage that isn't
last therefore silently degrades to an intermediate confirmation, so
`GET /routes/{id}` reports `initiator_stage_not_last` — a warning for the
editor, not a block (blocking would forbid ever appending a stage after a
signature). A signature stage on a process started **without** an initiator,
or whose initiator is deactivated, refuses the start with 409.

**Conditional branches.** A stage may carry a `condition` — a flat list of
predicates, ANDed, over *facts* the domain app supplies. Within an `order`
group, only stages whose condition matched enter the process; a stage flagged
`is_fallback` stands in when nothing in its group matched. There is no branch
model: the branch *is* the `order` group. Signoff never learns what a fact
means — the domain app registers `facts(subject_id)` and `fact_fields()`
alongside its other callbacks, and `GET /subjects` republishes the schema so
the route editor can render a dropdown of, say, countries.

```jsonc
// stage condition — [] means "always"
[{"field": "admin_country_id", "op": "in", "value": [1, 4]}]
// ops: eq | in | not_in | gt | gte | lt | lte
```

Branches are resolved **once, at start**, before the snapshot. An `order`
group that ends up empty **refuses the start with 409** rather than silently
skipping a whole tier of approvers — the single most dangerous outcome here
is a budget quietly reaching final sign-off without financial control.

Stages are **snapshotted onto the process at start**, so editing a route —
or the subject — never disturbs approvals already in flight.

| Endpoint                                    | Method | Auth | Notes |
|---------------------------------------------|--------|------|-------|
| `/api/signoff/v1/enums`                     | GET    | jwt   | Choice labels for quorum, `approver_kind`, and every state enum — process, stage, task, and the subject's own `approval_state` |
| `/api/signoff/v1/subjects`                  | GET    | jwt   | Registered subject types, their labels, `has_active_route`, and `fields[]` — the facts that type allows branching on, with `options` for `choice` fields. This is what the route builder picks from |
| `/api/signoff/v1/routes`                    | GET    | jwt   | `?subject_type=&is_active=` |
| `/api/signoff/v1/routes`                    | POST   | admin | 409 if the subject type isn't registered, or a second active route |
| `/api/signoff/v1/routes/{id}`               | GET / PATCH, DELETE | jwt / admin | GET also returns `coverage_gaps[]` — `choice` values with no branch in their group — and `initiator_stage_not_last`. Both are warnings for the editor, not blocks; the list endpoint omits them (too costly per row) |
| `/api/signoff/v1/routes/{id}/stages`        | POST   | admin | `{order, name, quorum, approver_ids[], condition?, is_fallback?, approver_kind?, requires_attachment?}`; ≥1 approver for `named` and **none** for `initiator` — both enforced by the schema (422). Unknown ids → 409, and a condition naming an unknown field or an out-of-book value → 409 |
| `/api/signoff/v1/stages/{id}`               | GET / PATCH, DELETE | jwt / admin | PATCH replaces `approver_ids` **wholesale**; omitting the key leaves them alone. Same for `condition` — omit to keep, send `[]` to clear. Switching `approver_kind` to `initiator` clears the approver list for you; sending a non-empty list alongside it is a 409. The last stage of a route can't be deleted |
| `/api/signoff/v1/processes`                 | GET    | jwt   | `?subject_type=&subject_id=&state=&initiator_id=` |
| `/api/signoff/v1/processes`                 | POST   | admin | Deliberately narrow — it accepts *any* `subject_id` of any type and so would bypass domain permissions. **The real submit path is the domain endpoint** (`/api/contracts/v1/budgets/{id}/submit`, …) |
| `/api/signoff/v1/processes/{id}`            | GET    | jwt   | Full card: stages, tasks, approver names, subject title/url, plus `subject_facts` and each stage's `condition`/`matched_by` (`always`\|`condition`\|`fallback`) — the record of *why* these approvers |
| `/api/signoff/v1/processes/{id}/cancel`     | POST   | jwt   | Initiator **or** admin — checked on the row. Cancel ≠ reject: the object returns to `draft` |
| `/api/signoff/v1/processes/{id}/rework`     | POST   | jwt   | `{comment?}` — return an **already decided** object for rework, the only way to unlock an `approved`/`rejected` row for editing. **Approver of that process or admin** (initiator deliberately excluded — that would override someone else's decision); 409 while the round is still running (use the `rework` decision or cancel instead), 409 if the object is already open. The process moves to state `rework`, keeps its original `finished_at`, and the rework is journalled as a `reopened` event |
| `/api/signoff/v1/tasks/mine`                | GET    | jwt   | The inbox. Only `pending` tasks on **active** stages — a request on a stage the process may never reach is not "waiting on you" |
| `/api/signoff/v1/tasks/{id}/decision`       | POST   | jwt   | `{decision: "approve"\|"reject"\|"rework", comment?}`. The **named approver** decides; an admin token on someone else's task gets 409. On a `requires_attachment` stage, approving before the document is uploaded is a 409 (neither negative decision needs the PDF). `reject` and `rework` both close the whole round from that stage; they differ only in the subject: rejected stays locked, reworked becomes editable again |
| `/api/signoff/v1/tasks/{id}/attachment`     | POST   | jwt   | **multipart**, field `file` — the PDF for a `requires_attachment` stage, uploaded *before* the decision (the upload must not sit inside the transaction holding the process lock). Only the task's own addressee: **no admin override**, since uploading for someone else would forge their signature. PDF-only and ≤25 MB by media_files scope policy (`signoff_doc`, magic-byte checked) → 415/413 pass through verbatim. Re-uploading replaces the previous file while the task is still pending |

`subject_title` / `subject_url` on process cards and inbox rows come from the
domain app's `describe` callback — signoff cannot name a row it isn't allowed
to import. For contracts those URLs are `/contracts/budgets/{id}`,
`/contracts/counterparties/{id}`, `/contracts/agreements/{id}`; **those SPA
routes do not exist yet.**

**409 Conflict** covers: no route configured, the object is already under
approval, every approver on a stage is deactivated, no branch matched in a
group (and no fallback), a condition naming a fact the subject doesn't
supply, the process is closed, the task is addressed to someone else, it was
already decided, a signature stage with no (or a deactivated) initiator,
approving a `requires_attachment` stage with no document, or attaching one to
a stage that doesn't ask for it. `403` is only ever a permissions answer; `422` only ever
a schema one (an unknown condition operator lands here, not in 409).

---

## Django admin — `/django-admin/`

Replaces the old `sqladmin` aggregator. Standard Django admin, session +
login-form authenticated against the same `User` model (**not** the
`admin_session` JWT cookie — see Authentication above). Every domain's
`ModelAdmin` is wrapped in `htqweb.admin_gate.ServiceGatedAdminMixin`, so a
disabled app (`ServiceStatus.enabled=False`) disappears from the admin
index and its change/add/delete views 403 — the one exception is
`ServiceStatus` itself (`apps/core/admin.py`), reachable unconditionally so
disabling `core` can never lock an operator out of the only switch that
could re-enable it.

```
GET /django-admin/         → redirect to /django-admin/login/ if not authenticated, else the index
```

---

## Health checks

Two layers now — don't confuse them:

**Gateway (nginx, prod only):**
```
GET /health         → 200 {"status":"ok","gateway":"nginx"}        (static; doesn't touch Django)
GET /health/ready    → 200, or 503 {"status":"degraded","gateway":"nginx","upstream":"backend"}
                       (proxies to the backend's /api/core/v1/services/)
```

**Backend (Django, `apps/core`, mounted at the URL root — hit the backend's
own port directly, these are not under `/api/`):**
```
GET /health/               → 200 {"status":"ok","service":"backend","timestamp":"..."}
GET /health/ready/         → 200 {"status":"ok"} or 503 {"status":"unavailable"}  (checks DB with SELECT 1)
GET /api/core/v1/services/ → 200 {"services": {"users": true, "hr": true, ..., "conference": true}}
```
`/api/core/v1/services/` is what `docker-compose.yml`'s own healthcheck for
`backend-web` polls, and what nginx's `/health/ready` proxies to — it's the
more useful one operationally (per-domain enabled/disabled, not just "the
process is up").

---

## Internal conventions (replacing the old cross-service contract)

There is one process family now, not nine independently-deployed services —
most of what used to be a network contract between services is an
in-process Python contract instead.

| Concern              | Rule                                                              |
|------------------------|---------------------------------------------------------------------|
| **HTTP API**          | `htqweb.http.api_view` normalizes every response; errors are always `{"detail": ...}` (401/403/404/422/500/503), matching the old FastAPI envelope. |
| **Health**            | See above — gateway-level `/health`/`/health/ready` and Django-level `/health/`/`/health/ready/`/`/api/core/v1/services/` are different things. |
| **Request ID**        | Gateway emits `X-Request-ID`; `htqweb.middleware.request_id.RequestIDMiddleware` echoes/generates it and puts it on `request.request_id`. |
| **JWT validation**    | Every app decodes the JWT the same way, in-process (`htqweb/authn/jwt.py`), HS256, shared `JWT_SECRET`. No introspection, no S2S JWT anymore — the Django port explicitly dropped the old `SERVICE_JWT_SECRET`/`X-User-Id` service-to-service concept (see `apps/media_files/views.py`'s `_can_access_private` docstring). |
| **User context**      | `request.token.user_id` (int) is the source of truth for the calling user. |
| **Authorisation**     | `is_staff`/`is_superuser`/`is_admin` claims (`TokenPayload.is_elevated`) gate admin paths, via `api_view(admin=True)` / `htqweb.authn.rbac.require_admin`. |
| **Cross-app calls**   | A neighbour app is reached only through its `apps.<x>.interface` module — a plain Python function call, not HTTP. Every `interface.py` function starts with `require_service("<name>")`, so a disabled dependency degrades the same way an external call would (`ServiceDisabled` → 503 envelope), instead of a raw exception. |
| **Logging**           | structlog-style JSON to stdout → Promtail → Loki. |
| **Database**           | One Postgres schema (`public`), one connection per app process (`CONN_MAX_AGE=0`, direct to `db:5432`, no PgBouncer in the request path). Table names are Django's own `<app_label>_<model>` default. |
| **Migrations**        | Plain Django `makemigrations`/`migrate`, `managed=True`. No Alembic. |
| **Pub/Sub**            | Redis pub/sub survives for exactly one purpose now: bridging `apps.approvals`' SSE stream across the WSGI/ASGI process split (see the SSE section above). The old `user.upserted`/`user.deactivated` replication channels were dropped — neighbours call `apps.users.interface` directly instead of consuming an async replica. |
| **Worker queue**      | Celery, Redis broker. One `backend-worker` + one `backend-beat` for the whole platform (not one pair per domain anymore). Every task's first line is `require_service("<app>")`. |

---

## Rate limiting (nginx prod only)

| Zone            | Rate        | Applied to                                              | Burst |
|-------------------|-------------|------------------------------------------------------------|-------|
| `api_general`     | 30 req/s    | `/api/` (catch-all), `/api/media/`                          | 20    |
| `api_public`      | 10 req/min  | `/api/hr/v1/public/`                                        | 5     |
| `media_upload`    | 5 req/s     | `POST /api/media/v1/files/`                                  | 10    |
| `websocket`       | 10 req/s    | `/ws/sfu/` (burst 5), `/ws/` (burst 20)                       | 5–20  |
| `api_auth`        | 5 req/min   | *(zone defined in nginx, not currently attached to any `location`)* | —     |

`/api/email/v1/webhooks/` is explicitly exempt from rate limiting (webhook
senders retry aggressively; false-positive 429s would just cause more
retries). Vite dev proxy doesn't enforce rate limits at all.

---

## Error responses

Same envelope as the FastAPI generation — `htqweb.http.api_view` was built
to match it byte-for-byte so the frontend's error handling didn't need to
change:

```json
{ "detail": "human-readable message" }
```

| Status | Meaning                                                           |
|----------|---------------------------------------------------------------------|
| 400      | Validation / malformed request (`SuspiciousOperation`)               |
| 401      | Missing or invalid JWT                                               |
| 403      | Authenticated but not authorised (e.g. non-admin on admin route), or `django-admin` `PermissionDenied` |
| 404      | Resource (or route) not found — see the routing table above          |
| 409      | Conflict (e.g. duplicate email on register)                          |
| 422      | Pydantic validation error (`body=` schema on `api_view`)              |
| 429      | Rate limit exceeded (nginx prod only)                                |
| 500      | Unhandled exception — `api_view` catches everything and logs it       |
| 503      | A dependency's `ServiceStatus` is disabled (`{"detail","code":"service_disabled","service"}`), or upstream unhealthy at the gateway |

---

## Browser cache pitfalls

1. **HSTS sticky after dev TLS** — see the box at the top of this file.
2. **Service Workers** — none registered today, but if you saw stale data
   after an asset update: DevTools → Application → Service Workers →
   *Unregister*, then hard reload (Ctrl+Shift+R).
3. **JWT in localStorage** — kept under `htq_access` / `htq_refresh`.
   On 401 the client tries `POST /api/users/v1/token/refresh/` once; if
   that also 401s, the storage is cleared and the user is redirected to
   `/login`.
4. **Stale Vite bundle** — Vite invalidates ESM modules on file save;
   if HMR is silent, hard reload.
