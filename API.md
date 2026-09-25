# API Documentation — HTQWeb Platform

> **State: post-cutover (phase 11 complete).** The nine FastAPI microservices
> and the Django monolith that preceded them are both gone. One Django
> backend (Python 3.14, Django 5.2.7) now serves every domain behind a Vite
> dev proxy (`:3000`) or the nginx prod gateway (`:80`). Real-time chat over
> Socket.IO, served by the backend's ASGI process. One Postgres database:
> shared apps in schema `public`, the tenant apps (`hr`, `tasks`,
> `contracts`, `signoff`) in one schema per company (`co_<slug>`).

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
│                          static. Only this process migrates          │
│                          (`migrate_shared` — shared apps only) +     │
│                          seeds the admin account (RUN_BOOTSTRAP=1;   │
│                          migrations — RUN_MIGRATIONS=1)              │
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
│   public (shared apps) + co_<slug> per company (TENANT_APPS) +       │
│   holding (UNION ALL views). Table names are Django's own default    │
│   (<app_label>_<model>, e.g. hr_department, mail_emailaccount)       │
│   PgBouncer :6432 kept for host tooling only, not live traffic       │
│ Redis :6379  (cache, Celery broker/results, SSE pub/sub bridge)      │
│ Loki :3100, Grafana :3002 (prod :3001), Prometheus :9090             │
└──────────────────────────────────────────────────────────────────────┘
```

Domains are Django apps under `backend/apps/`: `users`, `hr`, `tasks`,
`approvals` (mounted at `/api/requests/`), `cms`, `media_files` (mounted at
`/api/media/`), `mail` (mounted at `/api/email/`), `messenger`, `contracts`,
`signoff`, `conference`, `companies` (the group's company registry) and
`access` (roles and permissions), plus `core`
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

`docker compose --profile production up -d` brings up nginx on
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
| `/api/conference/v1/*`              | `backend` (WSGI)   | История видеоконференций, записи, протокол — **не** `/api/cms/v1/conference/*` (там конфиг SFU и приглашения) |
| `/ws/`                              | `backend_asgi`     | Messenger Socket.IO, mounted at `ws/messenger/socket.io` |
| `/ws/sfu/`                          | `sfu` (mediasoup)  | WebRTC signalling for `/conference` — not Django. JWT обязателен: подпротокол `htqweb.jwt`, `Authorization: Bearer` или `?token=` (иначе 401 на upgrade) |
| `:4433/udp` (в обход nginx)         | `webtransport`     | QUIC-сигналинг того же SFU: браузер ходит прямо на UDP-порт, nginx его не проксирует. Токен — в `?token=` |
| `/api/admin/v1/*`                   | `backend` (WSGI)   | Infrastructure panel — **admin-only**, see the section below |
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
{ sub, user_id, username, email, is_staff, is_superuser, is_admin,
  company, token_type: "access" | "refresh", iat, exp, iss }
```
`is_admin = is_staff OR is_superuser`. `company` is the slug of the company
the token was issued for — the request's company (`X-HTQ-Company`;
membership required, otherwise login/refresh answer 403 and issue no
token — with one exception: an archived company issues a token to a
superuser only, membership or not, and to nobody else, members included;
see [the archive spec](docs/plans/2026-09-25-archive-read-only-spec.md));
without the header — the user's default active company
(`apps/users/views.py::_company_slug_for_token`,
`htqweb/authn/jwt.py::_base_claims`). A refresh token carries only `sub`,
`user_id`, `iss` plus the type/time claims. `apps.users` (`htqweb/authn/jwt.py`)
both issues and validates every token, in-process, for every app — no
introspection round-trip, no separate identity service.

### Authorization — one rule: JWT + company + `module × level`

Stated once here; the per-domain tables below do **not** repeat it per row.

1. **JWT** (`Authorization: Bearer`) — every `/api/*` route unless marked
   *Public* / `auth=None`.
2. **Company context** — `X-HTQ-Company: <host label>` (nginx sets it from the
   subdomain; the SPA and any client on a subdomain gets it for free). Since
   block I.2 the label is the company's short alias `Company.subdomain`
   (`htq`, `hts`, `keg`, `group`) or, for a company **without** an alias, its
   slug — `apps.companies.interface.resolve_host_label`. Each company has one
   canonical host: the slug-host of a company that has an alias answers
   **404**, same as an unknown label. From there on everything uses the slug
   (schema, token claim, role assignments). The bare domain carries no company:
   the SPA sends a signed-in user to `/companies/choose` there. The
   token's `company` claim must equal the header's company, otherwise
   **403** — a subdomain is trivial to spoof, a signature is not. Switching
   company means moving to that company's host: the SPA there has no access
   token of its own (it is per-origin) and exchanges the refresh token, kept
   in a cookie on the parent domain, for one issued for that company
   (`frontend/src/lib/auth/sessionRestore.ts`, `companySwitch.ts`) — no
   second login. Both login and refresh refuse (**403**) a company the user
   has no `CompanyMembership` in.
3. **Module × level** — a route declared `api_view(module="<m>",
   level="read"|"write"|"admin")` asks `apps.access` for the caller's level
   on that module *in the request's company* and answers **403** when it is
   below the declared one. The level is the projection of the caller's roles
   (`GET /api/access/v1/me` → `permissions[<m>].level`), computed from
   `PositionRole` (roles of the position they hold, incl. inherited from a
   serving ancestor company) plus personal `RoleAssignment`. **Without a
   company context the level is `none` for everyone but a superuser** — the
   only free pass left; `is_staff`/`is_admin` alone open nothing.
   `admin=True` on a route is the platform-admin predicate and is checked
   in addition, not instead.
4. **Finer than the level** — inside a route the domain may check a single
   function-registry node (`apps/hr/rbac.py::NodeAccess.has`, e.g.
   `hr.employees` with flag `delete`), because the module level aggregates
   over the whole subtree (`hr-senior` reaches `admin` on `hr` through
   `delete` on org/staffing/calendar without being allowed to delete
   employees). Such checks answer 403 with the domain's own detail — in
   `hr` most often `{"detail": "Missing permission: <old key>"}`, where the
   key is the legacy permission name the node check was asked for (e.g.
   `hr.calendar.manage`), not `<node>.<flag>`. The *scope* of a grant (`department` vs `company`,
   `/me` → `permissions[<m>].scope`) narrows the data a read returns
   (employee list of one's own department), not the route's availability.

**Which routes carry the gate.** Every route of the five apps `hr`, `users`,
`companies`, `access` and `tasks` — enforced by the inverted guard in
`apps/access/tests/test_gate.py` (every route outside the registry must carry
`module=`, always with an explicit `level=`) — except the ones listed in the
self-service registry `apps/access/self_service.py`, each with a declared
reason: `self` (returns strictly the caller's own data, e.g.
`GET /api/hr/v1/employees/me`, `/api/users/v1/profile/me`,
`GET /api/companies/v1/me`), `open` (a company-wide reference such as
`GET /api/hr/v1/org/tree`, deliberately readable by any signed-in employee) or
`scoped` (protected by its own non-role check — one's own department's files,
being the approver of a given identity request; the platform operations of
`companies` — archive, restore, revoking a membership — which only a
superuser may call: `admin=True` plus `is_superuser` in the method). Those
three share one decorator factory, `platform(...)` in
`apps/companies/views.py`, and the registry lists the factory once
(`"platform": "scoped"`) — so **any new route put on `@platform` becomes
`scoped` automatically** and must call `deny_unless_platform_admin` first,
like the three existing ones; the guard cannot tell it apart. The
destructive `hr` routes that used to be open to anyone signed in
(`DELETE /vacancies/{id}/`, `/applications/{id}/`,
`/time-tracking/entries/{id}/`, `/documents/{id}/`) are gated at `hr: admin`
— the third deliberate exception of block I; creating and editing those
resources stays open. `contracts` and `signoff` are **not** gated yet —
their owners add `api_view(module=…)` themselves (roadmap §6.2/6.3); until
then they follow the older "read = JWT, write = admin / explicit
permission" wording in their own sections.

The seeded roles: `platform-admin` (`access/migrations/0002`);
`employee-basic` (`0004` — profile, messenger, conference (join only), mail,
tasks, calendar, news, requests), granted to a new member together with the
membership (`membership_service.grant_membership` →
`access.interface.ensure_basic_role`) and to members that existed at rollout
by `manage.py access_backfill_basic`; `hr-junior` (hr: read, own department),
`hr-middle` (hr: write, own department), `hr-senior` and `hr-lead` (hr:
admin, whole company) — `0005`, sub-node denies `0008`. Positions get
them through `PositionRole` (`PUT /api/access/v1/positions/{id}/roles`, or
`manage.py access_backfill_positions` once, at rollout — a position whose
old explicit key list replaced its level preset gets a named role
`hr-custom-<slug>-<id>` instead of a level role).

What the rollout moves over, and what it deliberately doesn't:

- A named role belongs to its company (`Role.company_slug`, see
  `apps.access` below). Its nodes are the union of the flags of every listed
  key that maps to the node, so keys of one node **add up**: the role answers
  "yes" to a neighbouring old key of the same node whose flags it covers —
  the same property the level roles have.
- **Deliberate exception #4 of block I:** a position whose list holds only
  `contracts.*` keys gets no HR role at all. The old model let its holder
  into HR routes gated by the bare level (`HRAccess.has_access` was "a level
  OR any key"), though the list granted no HR key; the migration summary
  prints such positions as «явный список без кадровых ключей», and
  `contracts` keeps reading its keys from `Position.permissions` itself.
- The holder's HR card is found by `user_id` and then by the token's email,
  as the old resolver did. That cannot be used to claim someone else's card:
  self-registration is moderated — the account stays `PENDING` until an
  admin approves it (`/api/users/v1/pending-registrations/`), and login and
  refresh issue tokens to `ACTIVE` accounts only.
- Revoking a membership (`DELETE …/memberships/{user_id}`) leaves the user's
  `PositionRole`/`RoleAssignment` rows in place (customer decision). They are
  inert: without a membership neither login nor refresh issues a token for
  that company (`apps.companies.interface.user_may_enter_company`). Caveat:
  an access token issued before the revocation keeps working, with all its
  roles, until it expires (`JWT_ACCESS_TTL_MIN`, 60 min) — `api_view` checks
  the `company` claim, not the membership. That was already so before
  block I.2.
- A membership created in django-admin goes through
  `membership_service.grant_membership` too, so it gets `employee-basic` like
  every other path.

### Refresh token

```
POST /api/users/v1/token/refresh/
Content-Type: application/json

{ "refresh": "<jwt>" }
→ 200 { "access": "<jwt>", "token_type": "Bearer" }
→ 403 { "detail": "Forbidden" }   # X-HTQ-Company names a company the user has no membership in
```
The new access token is issued for the request's company, not for the one
the refresh token was first issued in (a refresh token carries no
`company`); without `X-HTQ-Company` — for the user's default company.

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
start (`RUN_BOOTSTRAP=1` → `docker-entrypoint.sh` → a `manage.py shell`
one-liner, after collectstatic and bucket creation). `RUN_BOOTSTRAP` is
separate from `RUN_MIGRATIONS` (which only gates `migrate_shared`) and is
`1` in all three compose files (a `${RUN_BOOTSTRAP:-1}` default in
`docker-compose.yml`/`test-env`, hard-coded in `test-local`), so the admin
is seeded even where migrations are off:
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
| `/api/hr/v1/employees/users/`             | GET, POST | User picker for "create employee from user" (`?search=`, `?limit=`); each row carries the data that can be pulled into a card plus `employee_id` ("already has a card"). POST creates the platform user via `apps.users.interface.create_user` |
| `/api/hr/v1/employees/sources/mailboxes`  | GET    | Corporate mailboxes as a prefill source (`?search=`, `?unassigned=1`). Empty list — not 503 — when `apps.mail` is disabled |
| `/api/hr/v1/employees/prefill`            | POST   | Preview a transfer: `{source: {type: user\|employee\|mailbox, id}, employee_id?}` → per-field `fill`/`conflict`/`same` diff. Writes nothing |
| `/api/hr/v1/employees/{id}/prefill/apply` | POST   | Apply the ticked fields only; a field absent from the preview is ignored. `department_id`/`position_id` additionally require the transfer permission |
| `/api/hr/v1/employees/match-suggestions`  | GET    | "This person may already exist": similar user accounts and similar employee cards, by email/phone/name |
| `/api/hr/v1/employees/import-candidates`  | GET    | User accounts that have no employee card yet |
| `/api/hr/v1/employees/bulk-import`        | POST   | Create cards in one batch; answers with `{created, skipped: [{user_id, reason}]}` — a partially successful batch is a result, not an error |
| `/api/hr/v1/departments/`                 | GET, POST | Tree (`ltree path`)         |
| `/api/hr/v1/departments/tree`             | GET    | Full tree                      |
| `/api/hr/v1/positions/`                   | GET, POST |                              |
| `/api/hr/v1/positions/levels/`            | GET, POST | Level thresholds                |
| `/api/hr/v1/positions/{id}/substitutions` | GET, POST | Substitution matrix — GET: JWT, POST: admin=True |
| `/api/hr/v1/substitutions/{id}`          | PATCH, DELETE | Edit/delete (admin=True) |
| `/api/hr/v1/approvals/{subject_type}/{id}/submit` | POST | Отправить кадровый объект на согласование через `apps.signoff`. JWT, БЕЗ `admin=True` — отправляет тот, кто завёл заявку, а решает маршрут. `subject_type` — один из десяти `hr.*` (матрица HR-FRM-004, список в roadmap §6.4); 404 — неизвестный тип или нет такой строки, 409 — маршрут не настроен / объект уже на согласовании / в этапе не осталось согласующих / объект заперт. Ответ — карточка процесса с этапами |
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
| `/api/hr/v1/holding/headcount`            | GET    | Сводка по группе: люди/структура/штат по каждой действующей компании (блок H, `holding.*` через `apps/hr/holding_models.py`). JWT + гейт `module="hr", level="read"`, ПЛЮС только поддомен компании вида «холдинг» (`apps.companies.interface.is_holding`) — платформенный админ проходит всегда; 403 с чужого поддомена, 503 пока `migrate_companies` пересобирает представления |

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
| `/api/tasks/v1/staff-reports/projects/`           | GET    | Проекты, по которым вызывающему разрешено вести численность. Питает селектор страницы: роут-гейт фронта шире серверного правила (в токене нет ролей вида `hr_manager`), и сузить список может только сервер |
| `/api/tasks/v1/projects/{id}/staff-board/`        | GET    | Доска численности на `?date=`: блок × (факт, план из `ResourceRequirement(kind=human)`, сверка с `Σ DailyReport.headcount`). Строка есть у каждого блока, даже пустая |
| `/api/tasks/v1/projects/{id}/staff-reports/`      | GET, POST | Отчёт по ПЕРСОНАЛУ: сколько людей и каких ролей стояло на блоке. Один блок × одна дата = один отчёт (`UNIQUE` есть, в отличие от ежедневки: численность — состояние, а не сумма смен) |
| `/api/tasks/v1/staff-reports/{id}/`               | GET, PATCH, DELETE | PATCH заменяет строки целиком и пишет снимок; смена проекта/блока → 422; DELETE мягкий |
| `/api/tasks/v1/staff-reports/{id}/revisions/`     | GET    | Лента версий со снимком строк (имя роли внутри снимка) |
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
| `/api/tasks/v1/holding/projects`                  | GET    | Сводка по группе: проекты/объекты/задачи/отчётность по каждой действующей компании (блок H, `holding.*` через `apps/tasks/holding_models.py`). JWT + гейт `module="tasks", level="admin"` (`is_staff` без роли не проходит), ПЛЮС только поддомен компании вида «холдинг» (`apps.companies.interface.is_holding`) — платформенный админ проходит всегда; 403 с чужого поддомена, 503 пока `migrate_companies` пересобирает представления |

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
| `/api/email/v1/accounts/{id}/signature/`             | PATCH  | The employee's email signature for that address (`{signature}`, max 4000 chars). Stored per **account**, not per user — a work mailbox and a personal one should not sign the same way. The frontend inserts it into the compose editor rather than the backend appending it on send, so the sender sees what goes out under their name. `404` for an account that is not yours |
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
| `/api/email/v1/mailboxes/`                           | GET, POST | Corporate mailbox provisioning (admin). POST first **reconciles the address** — if that mailbox already exists (locally or on the mail server) and there is a `user_id` to give it to, it is **attached** instead of duplicated, and the response carries `attached: true` + `detail`. Otherwise it really creates the mailbox on the mail server; `502` + `{detail, mailbox}` when the server refuses (the local row survives, flagged `status=error`), If the found mailbox is attached but the platform could not obtain credentials for it (plain IMAP, or Mailcow refusing an app-password), the response carries `awaiting_password: true` — the mailbox is linked and visible, and the **employee** enters the password from their profile, the Mail section, or the post-login banner. Send `attach_if_exists: false` to force a brand-new address |
| `/api/email/v1/mailboxes/lookup/`                    | GET    | The same reconciliation as a preflight, so the create form can say what the button will do. Query: `address=`, or the create-form fields `local_part=`/`email=`/`first_name=`/`last_name=`, plus optional `user_id=`. A **corporate** `email=` wins over the transliterated name — `ruslan.amirov@htq.group` names the address outright, so guessing `r.amirov` from the full name would both misname the mailbox and look up the wrong one. Returns `exists`, `source` (`none`\|`local`\|`remote`\|`both`), `checked_remote`, `owner_user_id`, `owner_conflict`, `can_attach`, `needs_password`, `detail`. `checked_remote: false` means the server could not be asked (plain IMAP has no such command, Mailcow unreachable, no server configured) — deliberately **not** the same as "no such mailbox" |
| `/api/email/v1/mailboxes/status/`                    | GET    | What the connected mail server can do — `provisioner` (`mailcow`\|`imap`\|`none`), `domain`, `can_create_remotely`, `can_list_remote`, `allow_self_service`. The admin UI reads it to avoid promising what the server can't do |
| `/api/email/v1/mailboxes/settings/`                  | GET, PUT | Mail-server credentials, editable from the UI. Response splits `value` (stored in the DB; empty = inherit) from `effective` (what actually applies), plus `overridden` listing which fields the DB wins. The Mailcow API key is write-only — `mailcow_api_key_set` is the only thing read back; `""` means "leave unchanged", `null` clears the override |
| `/api/email/v1/mailboxes/settings/test/`             | POST   | Runs the same check chain as `manage.py mail_check` and returns it as `{ok, steps[]}` — each step carries `status` (`ok`\|`fail`\|`skip`), `detail`, an actionable `hint`, and `data` (e.g. the server's real folder list). Passwords are never echoed back |
| `/api/email/v1/accounts/connect-imap/`               | GET, POST | **Non-admin.** Connect any mailbox over IMAP/SMTP — the third way to add mail, next to OAuth and the corporate mailbox. GET (`?address=`) returns suggested server settings (known providers verbatim, otherwise `imap.<domain>` flagged `guessed`); POST verifies the credentials with a live IMAP login **before** writing anything. No domain restriction — this is the user's own mailbox, not a platform resource |
| `/api/email/v1/accounts/{id}/imap-password/`         | POST   | **Non-admin.** Update the stored password after changing it on the server; the new one is verified by logging in, so sync cannot silently stall |
| `/api/email/v1/accounts/connect-corporate/`          | GET, POST, DELETE | **Non-admin.** An employee supplies the password for their corporate mailbox (`{address, password}` verified by a live login before anything is written). GET reports `allowed`, `self_service`, `domain`, `own_address` (the employee's own corporate address, resolved server-side so the form need not be trusted), the current mailbox and `awaiting_password`; DELETE detaches it from the platform without touching the mail server. Normally requires `allow_self_service` — **except** two cases that carry no impersonation risk: the mailbox is already assigned to that employee and `awaiting_password` is true (refusing would mean "the mailbox is yours but you may not use it"), or the address equals their own platform email (an address the admin assigned them). The password is still mandatory and still verified by a live login in both — knowing an address proves nothing, since colleagues' addresses are on every email they ever sent. The address domain must match the corporate one, and a mailbox already owned by someone else is a `409` |
| `/api/email/v1/mailboxes/reconcile/`                 | GET, POST | Two-way platform ↔ mail-server reconciliation. GET = report only. POST body `{apply, direction}`, `direction` = `report`\|`pull`\|`push`\|`both`. Also links ownerless mailboxes whose address equals a user's email (`kind="unlinked"` → `action="linked"`, plus an `EmailAccount` for that user) |
| `/api/email/v1/mailboxes/{id}/`                      | GET, PATCH | Every mailbox payload also carries `awaiting_password` — linked to a user, no stored credentials, and a mail server that would need them |
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
| `/api/cms/v1/conference/invites`                     | GET, POST | Invite links for a room. GET `?room_id=`, POST `{room_id, title, allow_guests, ttl_hours, max_uses}` → `{url, …}` |
| `/api/cms/v1/conference/invites/{id}`                 | DELETE | Revoke an invite |
| `/api/cms/v1/conference/invites/{id}/send`            | POST | Send the link: `{emails[], user_ids[]}` → email + messenger notification, per-channel best effort |
| `/api/cms/v1/conference/join/{token}`                 | GET | **Public.** What the meeting is; `room_id` only for an authenticated employee |
| `/api/cms/v1/conference/join/{token}/guest`           | POST | **Public.** `{display_name}` → guest JWT (`token_type=guest`, bound to one `room_id`) + conference runtime config |

`conference/config` отдаёт: `sfu_signaling_url` (пустой = фронт берёт
`ws(s)://<origin>/ws/sfu/`), `sfu_signaling_path`, `ice_servers`, `enabled`
(флаг сервиса `conference` в реестре) и пару полей QUIC-сигналинга —
`wt_signaling_url` (адрес моста `webtransport`, пустой = мост не
анонсирован, работаем по WebSocket) и `wt_certificate_hashes` (DER SHA-256
самоподписанного сертификата моста для dev; с сертификатом от настоящего CA
список пуст).

## Conference history — `/api/conference/v1/*`

Аппка `apps.conference`: кто собрал встречу, когда, кто был, запись и
протокол. Не путать с `/api/cms/v1/conference/*` выше — там рантайм-конфиг
SFU и ссылки-приглашения; здесь то, что от встречи ОСТАЛОСЬ.

**Доступ:** участники встречи + `is_staff`/`is_superuser`. Чужому сотруднику
отвечаем **404, а не 403** — иначе перебором id можно узнать, что встреча
была, кто её собирал и как называлась. Гостевой JWT отбивается на уровне
`api_view` (`token_type="guest"` ≠ `access`).

| Endpoint | Method | Notes |
|---|---|---|
| `/api/conference/v1/sessions/` | GET | История: `?page=&limit=&q=&from=&to=&mine=1`. Конверт `{items,total,page,pages,limit,recorded_total,active_total}` — семь ключей намеренно, см. ниже |
| `/api/conference/v1/sessions/{id}` | GET | Карточка: участники, состояния, **подписанные** `recording_url`/`download_url`/`poster_url` |
| `/api/conference/v1/sessions/{id}/transcript` | GET | `?format=json` (по умолчанию) `\|txt\|md`; txt/md отдаются вложением |
| `/api/conference/v1/sessions/{id}/events` | GET | Журнал: вход/выход, камера, чат |
| `/api/conference/v1/sessions/{id}/recording` | GET | **302** на временную ссылку хранилища; `?download=1` — как вложение |
| `/api/conference/v1/sessions/{id}/poster` | GET | 302 на кадр-заставку |
| `/api/conference/v1/internal/sessions` | POST | **Только для SFU.** `{room_id, created_by_id, created_by_name}` → `{session_id, recording_enabled, …}` |
| `/api/conference/v1/internal/sessions/{id}/participants` | POST | `{peer_id, display_name, user_id, is_guest, action: join\|leave}` |
| `/api/conference/v1/internal/sessions/{id}/events` | POST | `{kind, peer_id, at_ms, payload}` |
| `/api/conference/v1/internal/sessions/{id}/artifacts` | POST | Сырые дорожки на общем томе |
| `/api/conference/v1/internal/sessions/{id}/finish` | POST | Комната опустела; ставит сборку в очередь |

**`recording` и `poster` объявлены `auth=None`, и это не дыра.** Тег
`<video src>` не отправляет заголовок `Authorization` — по обычному JWT плеер
до записи просто не достучался бы. Поэтому карточка встречи (там JWT есть и
права проверены) выдаёт ссылку с подписью `?sig=&exp=`, а эндпоинт проверяет
подпись вместо токена; обычный API-клиент по-прежнему может прийти с
`Bearer`. Схема подписи — общая с `htqweb/storage/signed_url.py`, привязана к
конкретной встрече: подпись от одной записи не откроет другую. Отдаётся
именно **302 на presigned-адрес**, а не байты через Django, — только так у
плеера остаётся `Range`, то есть перемотка.

**Внутренний канал закрыт общим секретом** `CONFERENCE_INTERNAL_TOKEN`
(заголовок `X-HTQ-Internal-Token`), а не JWT: у SFU нет пользователя, от чьего
имени ходить. Пустой секрет **закрывает** приём, а не открывает всем. Все
пять ручек идемпотентны — сеть между контейнерами теряет ответы, и повтор не
должен ни раздваивать встречу, ни запускать вторую сборку видео.

**Про семь ключей в конверте списка.** `unwrapPaginatedEnvelope`
(`frontend/src/api/client.ts`) разворачивает ответ в голый массив ровно
тогда, когда ключей пять — `{items,total,page,pages,limit}`. Лишние
`recorded_total`/`active_total` и оставляют конверт целым, так что пагинация
на странице истории работает (тот же приём, что у истории уведомлений с её
`unread_total`).

**Ретенция.** `expires_at = started_at + CONFERENCE_RETENTION_DAYS` (25 дней).
Celery-beat раз в сутки стирает медиа из хранилища и переводит встречу в
`recording_state="purged"`; строка истории, участники, события и текстовый
протокол сохраняются навсегда. Запрос записи у вычищенной встречи — 404 с
человеческим объяснением, а не пустой ответ.

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
| `/api/contracts/v1/advance-payments`             | GET, POST | Предоплата по договору; создание разрешено только когда `agreement.approval_state=approved` |
| `/api/contracts/v1/advance-payments/{id}`        | GET    | Карточка предоплаты |
| `/api/contracts/v1/advance-payments/{id}/submit` | POST   | **→ approval.** Возвращает карточку процесса (201) |
| `/api/contracts/v1/advance-payments/{id}/payment-order` | POST multipart | После одобрения предоплаты: «Файл платёжного поручения» + `posting_number`; нужен permission `contracts.advance_payment.record_payment` (или admin) |
| `/api/contracts/v1/advance-payments/{id}/payment-order-url` | GET | Signed URL платёжного поручения |
| `/api/contracts/v1/contract-payments` | GET, POST multipart | Оплата по договору: `administrator_id`, `agreement_id`, `amount`, файл `invoice`; администратор обязан совпадать с администратором бюджета договора |
| `/api/contracts/v1/contract-payments/{id}` | GET | Карточка оплаты |
| `/api/contracts/v1/contract-payments/{id}/submit` | POST | **→ approval.** После одобрения документ ожидает бухгалтерию |
| `/api/contracts/v1/contract-payments/{id}/invoice-url` | GET | Signed URL приложенного счёта |
| `/api/contracts/v1/contract-payments/{id}/payment-order` | POST multipart | После одобрения: `posting_number` + файл `file`; нужен permission `contracts.contract_payment.record_payment` (или admin) |
| `/api/contracts/v1/contract-payments/{id}/payment-order-url` | GET | Signed URL платёжного поручения |

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
stage names its HR positions explicitly. Their active employee accounts are
resolved when the process starts, and a `quorum` applies within each selected
position: `any` needs one holder of every position, while `all` needs every
holder of every position. **Any negative decision at any stage closes the whole process
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

* `approver_kind` — `position` (the default: HR positions listed in the
  route, whose current active employees/accounts are resolved **at start**) or
  `initiator`, where the single approver is resolved **at start** from
  `ApprovalProcess.initiator_id`. It is deliberately *initiator*, not
  "creator": signoff cannot read a domain model's `created_by`, and in
  contracts the two are the same person by business process. Such a stage
  must carry **no** `position_ids` (409/422 otherwise), and its `quorum` is
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
| `/api/signoff/v1/routes/{id}/stages`        | POST   | admin | `{order, name, quorum, position_ids[], condition?, is_fallback?, approver_kind?, requires_attachment?}`; ≥1 HR position for `position` and **none** for `initiator` — both enforced by the schema (422). Unknown ids → 409. The current active employee/account holders are resolved only when the process starts. |
| `/api/signoff/v1/stages/{id}`               | GET / PATCH, DELETE | jwt / admin | PATCH replaces `position_ids` **wholesale**; omitting the key leaves them alone. Same for `condition` — omit to keep, send `[]` to clear. Switching `approver_kind` to `initiator` clears the position list; sending a non-empty list alongside it is a 409. The last stage of a route can't be deleted |
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

## `apps.access` — `/api/access/v1`

Roles-and-permissions engine — stage-2 spec
(`docs/plans/2026-08-29-stage2-access-and-roles-spec.md` §4) frozen contract.
A role is a named set of function-registry entries (`node → depth flags`,
one of `view/create/edit/delete`); a position normally carries a set of
roles (`PositionRole`) — a personal `RoleAssignment` on a user is the
exception, for what a position can't carry (acting head, temporary
widening). **For a group of companies, cross-company access by position is
now also the normal path** (customer decision, 2026-09-15 — see block C
below and stage2-spec §1.2), not just within one company. The module-level
`level` (`none|read|write|admin`) inside `permissions` is a *projection* of
the finer `depth` map, kept for routing and the `api_view(module=)` gate —
`depth` is the source of truth for hiding individual fields/buttons.

| Endpoint | Method | Auth | Notes |
|---|---|---|---|
| `/api/access/v1/me` | GET | jwt | Caller's resolved permissions in the request's company — fields below |
| `/api/access/v1/functions` | GET | access/read | Function-registry tree (`module → function → field`) + flat page list, for the roles/permissions editor |
| `/api/access/v1/roles` | GET, POST | GET jwt (open); POST access/admin + superuser | Role catalog, `RoleRead.company_slug` included. A role with empty `company_slug` is shared by the group and acts the same in every company, so every catalog write is superuser-only. A role with `company_slug` set belongs to one company (block I.2 — today the named `hr-custom-*` roles of the rollout, migrations `access/0009`/`0010`): GET lists the shared roles plus those of the request's company; a superuser sees all |
| `/api/access/v1/roles/{id}` | PATCH, DELETE | access/admin + superuser | 409 deleting an `is_system` role |
| `/api/access/v1/roles/{id}/permissions` | GET, PUT | GET access/read; PUT access/admin + superuser | Depth flags per registry node for this role. GET of another company's role → 404, as if it didn't exist (PUT is superuser-only anyway) |
| `/api/access/v1/roles/{id}/holders` | GET | jwt (access/read) | Who holds the role — `position` (via `PositionRole`, fix by editing the position) vs `personal` (`RoleAssignment`, fix by editing the assignment) — named so a role can actually be unassigned before deletion. Another company's role → 404 |
| `/api/access/v1/roles/{id}/copy` | POST | access/admin + superuser | Duplicate a role's permission set under a new code/title; the copy keeps the source's `company_slug` |
| `/api/access/v1/positions/{position_id}/roles` | GET, PUT | GET jwt (open); PUT access/admin + `admin=True` | Roles carried by a position — the normal path, including the cross-company one described below. 422 for a role of another company — refused on every path that grants a role: this service check, and `PositionRole.clean()`/`RoleAssignment.clean()` for django-admin |
| `/api/access/v1/assignments/{user_id}` | GET, PUT | GET access/read; PUT access/admin + `admin=True` | Personal role assignments — the exception path. 422 for a role of another company, as above |

**`GET /me` response** (`MeRead`):

| Field | Type | Notes |
|---|---|---|
| `company` | `string \| null` | `null` outside a company context — transitional mode (roadmap §3), not an error |
| `permissions` | `{module: {level, scope}}` | Module-level projection; drives routing and `api_view(module=)` |
| `depth` | `{node: flags[]}` | Full picture by function-registry node; project fields/buttons by this, not by `permissions`. The client resolves a node by looking it up, then its ancestors — the first entry found is the answer (`frontend/src/lib/auth/permissions.ts::depthFor`). So the map carries a node only where its effective depth **differs** from what the client would inherit: an explicit role row equal to its ancestor's depth is left out, and a deny under a granted ancestor comes as an **empty list** (`hr.employees: ["view"]` + `hr.employees.salary: []`, the sub-node denies of `access/0008`) — the only case where `[]` means something; a node with no rights anywhere up the tree is simply absent. Sub-node `hr.employees.transfer` (transfer, change of position, dismissal — `edit` for `hr-senior`/`hr-lead`, deny for `hr-junior`/`hr-middle`) is one of those nodes |
| `hidden_pages` | `string[]` | Pages the role explicitly vetoes; a page not listed here follows the ordinary rules regardless of depth |
| `subordinate_companies` | `string[]` | Companies *below* this one in the ownership tree where the caller is manager by external hierarchy (`hr.Position.is_manager`/`external_hierarchy`, block B). Display only — doesn't filter data (stage2-spec §7) |
| `inherited_from` | `string[]` | **New in block C.** Companies *above* this one whose serving position (`hr.Position.serves_subsidiaries`) contributed part of `permissions`/`depth` above. Sorted; empty for a superuser and for anyone inheritance gave nothing. Ancestors are not mutually exclusive (customer decision 7) — a serving grandparent and a serving parent both contribute, so this can carry more than one slug |

**Holding rights in subsidiary companies (block C).** A position marked
`serves_subsidiaries=True` (separate from `is_manager`/`external_hierarchy`
— "runs the group's back office" and "manages people" are different
questions) carries its roles into every company below its own in
the ownership tree (`apps.access.services.inheritance`, walking `parent`
upward from the request's company, not the reverse): company-scoped,
unioned across every serving ancestor, and an archived ancestor is skipped
without stopping the walk further up. **This grants rights only** — the
holder still needs an explicit `CompanyMembership` in the subsidiary to get
a token for its subdomain at all (customer decision 3); `manage.py
company_grant --serving` grants it in bulk for a company, and the metric
`htqweb_access_serving_holders_without_membership` (`htqweb-domains`
dashboard) tracks who was marked serving but never actually granted
membership — the gap is invisible from the position screen alone otherwise.
A subsidiary can see (but not revoke) who from above holds rights in it via
`GET /api/companies/v1/companies/{slug}/external-holders` — see
`apps.companies` below.

---

## `apps.companies` — `/api/companies/v1`

Company registry for the schema-per-company tenancy design (CLAUDE.md,
"Мультикомпанейность"): `Company`, `CompanyModule` (per-company kill switch
layered on top of `apps.core.models.ServiceStatus`), `CompanyMembership`
(who may work in which company). `TENANT_APPS = (hr, tasks, contracts,
signoff)` live in `co_<slug>` schemas; `companies` itself lives in `public`
and needs no `X-HTQ-Company` header.

**Two auth shapes.** Read/write routes go through `api_view(module=
"companies", level="read"|"write")` — the caller needs that access level
for the `companies` module (`apps.access`), same mechanism as every other
domain. Archive, restore, bankruptcy and membership revocation are **platform-level**
instead: `api_view(admin=True)` (staff-or-superuser) plus an explicit
`is_superuser` check inside the view (`deny_unless_platform_admin`) — a
plain staff token gets 403. Archive/restore/bankruptcy/revoke are
irreversible-ish enough (archive turns every write on the company's
subdomain into a 403 `company_archived` — for everyone, superuser included, except `GET`/`HEAD`/
`OPTIONS` and the token endpoints — and every read of the company's data on
it into a 404 for anyone but a superuser: anonymous (`auth=None`) handlers of
the tenant apps (`hr`, `tasks`, `contracts`, `signoff`, e.g. HR share links)
404 too, while anonymous handlers of shared apps — signed file URLs,
messenger attachments, avatars, meeting recordings — keep answering, since
they read `public`, not the company's schema, and are signature-protected;
`django-admin` doesn't get even that exception and
404s regardless of who's asking, because the check runs before Django's own
session/auth middleware can tell; bankruptcy does all that and also hands
every member a membership in the successor, which restore does not take
back; revoke locks someone out) that "elevated"
isn't a high enough bar.

⚠️ **The module gate alone is company-blind.** `api_view(module=…)` resolves
the caller's level in *the caller's own company* (`current_company_or_none()`)
and never looks at the `{slug}` path segment being read or mutated — so on
its own it would let a `companies` writer in company A rename, re-parent, or
flip a module of company B, and let a `companies` reader in company A list
company B's module states or membership roster (`username`/`full_name`/
`email`). The final review of Block A caught this; the fix (present in the
rows below) is a second, explicit check inside the view: `PATCH
/companies/{slug}`, `PATCH …/modules/{app_label}` and `POST …/memberships`
additionally call `deny_unless_platform_admin` (same helper archive/restore
use — the registry is run by the platform administrator, not by peer
companies), and `GET …/modules` / `GET …/memberships` additionally call
`deny_unless_own_company`, which passes for a superuser or for the company
named in `X-HTQ-Company` and 403s everyone else. **A company's own
sub-resources (modules, memberships) are visible to that company and to the
platform administrator only.**

| Endpoint                                                | Method | Auth              | Notes |
|----------------------------------------------------------|--------|-------------------|-------|
| `/api/companies/v1/me`                                    | GET    | jwt               | Companies where the caller holds an active membership in an active company, ordered `-is_default, name`; `[{slug, subdomain, name, kind, is_default, is_current}]` — the SPA builds a company's host from `subdomain ?? slug` (switcher, `/companies/choose`); no module gate — every signed-in user needs this to switch companies. A superuser additionally gets every archived company in the registry appended, membership or not, each row carrying `is_archived: true` (`false` on every other row). An archived company is read-only: any method there but `GET`/`HEAD`/`OPTIONS` (the token endpoints excepted) is refused with 403 `company_archived` for everyone, and of the safe methods only a superuser gets through to read it — see [the archive spec](docs/plans/2026-09-25-archive-read-only-spec.md) |
| `/api/companies/v1/companies`                              | GET    | jwt (companies/read)  | `?status=all\|active\|archived`, default `all` |
| `/api/companies/v1/companies/tree`                         | GET    | jwt (companies/read)  | Active companies only, nested by `parent_slug`. A node whose parent got archived becomes a root instead of disappearing from the tree |
| `/api/companies/v1/companies/{slug}`                       | GET    | jwt (companies/read)  | 404 `not_found` for an unknown slug |
| `/api/companies/v1/companies/{slug}`                       | PATCH  | jwt (companies/write) + superuser | `{name?, kind?, country?, parent_slug?, show_external_holders?, subdomain?}` — `slug` itself never changes: it names the Postgres schema and is the company's value in tokens and role assignments. `subdomain` is the short host label (block I.2); `""`/`null` removes it (the company goes back to its slug-host), an omitted key leaves it alone; reserved labels (`www`, `api`, `admin`, `mail`, `static`, `cdn`, `grafana`, `media`, `sfu`, `ws`, `localhost`) and a label equal to another company's slug (or a slug equal to another's alias) are refused by `Company.clean()` → 422 `invalid`. A changed alias takes effect within the 5-second registry cache. `parent_slug: null` clears the parent; omitting any key leaves it alone (`model_fields_set`, not a `None` check). 422 `parent_not_found` / `parent_cycle` / `invalid`. `deny_unless_platform_admin` inside the view — see the company-blind-gate note above |
| `/api/companies/v1/companies/{slug}/archive`               | POST   | admin (superuser)     | Idempotent. 409 `last_active` if this is the only company with `status=active` — see below. Rebuilds holding views |
| `/api/companies/v1/companies/{slug}/restore`                | POST   | admin (superuser)     | Idempotent. Clears `successor` (the restored company lives on its own again); memberships already granted in the successor by a bankruptcy are **not** revoked. Rebuilds holding views |
| `/api/companies/v1/companies/{slug}/bankrupt`               | POST   | admin (superuser)     | Bankruptcy with a successor ([spec](docs/plans/2026-09-26-company-bankruptcy-spec.md), `lifecycle.bankrupt_company`; same operation as `manage.py company_bankrupt`). Body `{successor: "<slug>", dry_run?: false}`. Every member of `{slug}` with an **active** account gets a membership in the successor (`membership_service.grant_membership` — the new membership comes with `employee-basic`; a member whose default company was `{slug}` gets `is_default` on the new one; members already in the successor are left alone), then `{slug}.successor` is set and the company is archived (read-only) with a holding-view rebuild. **Only membership moves** — `hr` cards, equipment and contracts stay in the archive. Response `{company: CompanyRead, successor: CompanyRead, members_total, members_granted, members_already, archived, dry_run}`; `dry_run: true` counts and changes nothing (`archived: false`). Idempotent for the same pair: a repeat grants whatever is missing; `archived: false` when the company was already archived. An already-archived company without a successor can still be bankrupted. 403 for anyone but a superuser (a staff token included — `deny_unless_platform_admin`); 404 `not_found` for an unknown company or successor; 409 `successor_conflict` if the company already has a *different* successor, 409 `holding_stale` if the holding views could not be rebuilt (memberships and `successor` are already saved at that point; the views are finished by `manage.py migrate_companies`); 422 `successor_invalid` if the successor is the company itself or isn't active, 422 on a malformed body |
| `/api/companies/v1/companies/{slug}/modules`                | GET    | jwt (companies/read), own company only | One row per `KNOWN_SERVICES` entry: `{app_label, enabled, message, is_core}`. No stored `CompanyModule` row means enabled. `deny_unless_own_company` inside the view — see the company-blind-gate note above |
| `/api/companies/v1/companies/{slug}/modules/{app_label}`    | PATCH  | jwt (companies/write) + superuser | `{enabled, message?}`. 422 if `app_label` isn't in the platform service registry; 409 if it's one of `CORE_MODULES` — core modules can't be switched off per company at all. `deny_unless_platform_admin` inside the view — see the company-blind-gate note above |
| `/api/companies/v1/companies/{slug}/memberships`            | GET    | jwt (companies/read), own company only | Account fields joined in via `apps.users.interface.get_users_brief`. A membership whose account got deleted still shows, with blank account fields, rather than being hidden — a hidden row can't be revoked. `deny_unless_own_company` inside the view — see the company-blind-gate note above |
| `/api/companies/v1/companies/{slug}/memberships`             | POST   | jwt (companies/write) + superuser | `{user_id, is_default?}`. 422 if `user_id` doesn't resolve via `get_user_brief`. Idempotent on `(company, user_id)`: 201 on first grant, 200 on repeat, never a second row. `deny_unless_platform_admin` inside the view — granting membership hands out a legitimate `company` claim and that company's whole tenant schema, see the company-blind-gate note above |
| `/api/companies/v1/companies/{slug}/memberships/{user_id}`   | DELETE | admin (superuser)     | 409 `self_revoke` — can't revoke your own membership over HTTP (locking yourself out is one click; getting back in needs `manage.py company_grant` from a console). 404 if there's no such membership |
| `/api/companies/v1/companies/{slug}/external-holders`         | GET    | jwt (companies/read), own company only | Block C. Who from a company *above* this one in the ownership tree currently holds rights here through a serving position (`hr.Position.serves_subsidiaries` → `apps.access.services.inheritance`) — `[{full_name, home_company, position, modules: [{module, level}]}]`, exactly those four fields and nothing else (no email/phone/department — this is holding-staff data disclosed to the subsidiary). `deny_unless_own_company`, same as the membership roster. 403 with a body (not an empty list — an empty list would mean "nobody from outside holds rights here", which would be false) when `Company.show_external_holders` is off for this company |

**`show_external_holders`** (`CompanyRead`/`CompanyPatch`, migration `companies/0004`, default `true`) is a per-company, platform-admin-only setting: it controls whether a subsidiary can *see* who from a parent company holds rights in it via the endpoint above — it does not control the access itself, and a subsidiary cannot turn it off for itself (customer decision 4, block C). Defaulting to on is deliberate: hiding it by default would hide the fact of access from the company whose data is actually being read.

**`successor_slug`** (`CompanyRead`, read-only; a model property like `parent_slug`) is the slug of the company that took over a bankrupt one, `null` otherwise. It is set only by `POST …/bankrupt` / `manage.py company_bankrupt` and cleared by restore; the registry screen shows it on the company card as a «Преемник» row with the successor company's name.

**`subdomain`** (`CompanyRead`, `MyCompany`, `CompanyPatch`; migrations `companies/0005` field, `0006` seeds `hi-tech-qazaqstan → htq`, `hi-tech-systems → hts`, `kazakhstan-engineering-group → keg`, `hi-tech-group → group`; CLI `company_create --subdomain`) is the company's short host label, `null` when the company lives on its slug. It decides only which host resolves to the company (see "Company context" in the authorization rule above); links that must open a company page from outside — HR share links — are built by `apps.companies.interface.public_url(slug)` as `https://<subdomain or slug>.<host of PUBLIC_BASE_URL>`. Rollout checklist (DNS, origin certificate, `SFU_ALLOWED_ORIGINS`, order of commands, checks): [docs/deploy/subdomains-runbook.md](docs/deploy/subdomains-runbook.md).

**No HTTP company creation, on purpose.** `provision_company` runs a fresh
schema plus four apps' worth of migrations (~1 minute) before it's done;
`gunicorn --timeout 60` would kill the worker mid-DDL. Creation stays
CLI-only — `manage.py company_create`. Archive/restore/bankruptcy stay over HTTP
because they're a status flip (bankruptcy adds a membership row per member)
and a view rebuild, not DDL.

**Archiving the last active company is refused, not silently allowed.**
`archive_company` returns 409 `last_active` when the target is the only
company with `status=active`: for as long as the transition mode holds
(`docs/plans/2026-09-14-group-structure-roadmap.md` §3 — currently one
live company, "Hi-Tech Qazaqstan"), archiving it would leave the platform
with no active company to write to — every route on it, `contracts`/
`signoff` included, resolves its schema from the company on the request,
and a schema only a superuser can read (and nobody can write) isn't a
schema the platform can run on.

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
| **Authorisation**     | Application routes: `api_view(module=, level=)` — the caller's roles in `apps.access`, counted in the request's company (see Authentication → Authorization). Platform-admin paths: `is_staff`/`is_superuser`/`is_admin` claims (`TokenPayload.is_elevated`) via `api_view(admin=True)` / `htqweb.authn.rbac.require_admin`, checked in addition to the module gate in the five gated apps (`hr`/`users`/`companies`/`access`/`tasks`); elsewhere `admin=True` is the only gate. |
| **Cross-app calls**   | A neighbour app is reached only through its `apps.<x>.interface` module — a plain Python function call, not HTTP. Every `interface.py` function starts with `require_service("<name>")`, so a disabled dependency degrades the same way an external call would (`ServiceDisabled` → 503 envelope), instead of a raw exception. |
| **Logging**           | structlog-style JSON to stdout → Promtail → Loki. |
| **Database**           | One Postgres database: shared apps in `public`, `TENANT_APPS` (`hr`, `tasks`, `contracts`, `signoff`) in one `co_<slug>` schema per company, chosen per request by `search_path` (`CompanyContextMiddleware`); group-wide read views in schema `holding`. One connection per app process (`CONN_MAX_AGE=0`, direct to `db:5432`, no PgBouncer in the request path). Table names are Django's own `<app_label>_<model>` default. |
| **Migrations**        | Plain Django `makemigrations`, `managed=True`, no Alembic. Applied in two steps: `manage.py migrate_shared` (shared apps — what container start runs) and `manage.py migrate_companies` (each company's schema, a separate rollout step) — never bare `migrate` once `tenancy_bootstrap` has moved the tenant apps out of `public`. |
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
| `api_auth`        | 5 req/min   | `/api/users/v1/token`, `token/refresh`, `register` (exact-match, both spellings) | 2     |

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
| 403      | Authenticated but not authorised (e.g. non-admin on admin route, module level below the route's, token `company` claim ≠ the request's company), or `django-admin` `PermissionDenied` |
| 404      | Resource (or route) not found — see the routing table above; also `{"detail": "Компания не найдена"}` from `CompanyContextMiddleware` for a request to an unknown company's host, from `django-admin` on an archived company's host, or from `api_view` for anyone but a superuser reading an archived company (see the archive spec) |
| 409      | Conflict (e.g. duplicate email on register)                          |
| 422      | Pydantic validation error (`body=` schema on `api_view`)              |
| 429      | Rate limit exceeded (nginx prod only)                                |
| 500      | Unhandled exception — `api_view` catches everything and logs it       |
| 503      | A dependency's `ServiceStatus` is disabled (`{"detail","code":"service_disabled","service"}`), or upstream unhealthy at the gateway |

---

## `apps.core` — `/api/admin/v1/infrastructure` (admin only)

Порт снесённого admin-сервиса: страница «Инфраструктура» в профиле
администратора. Живёт в `apps.core`, потому что описывает платформу целиком,
а не какой-то один домен; маршруты объявлены в
[apps/core/urls.py](backend/apps/core/urls.py) полностью, вместе с префиксом —
у аппки нет `API_PREFIX`, она смонтирована в корень.

**Все роуты — `api_view(auth="jwt", admin=True)`.** Ослаблять гейт нельзя ни на
одном, включая health-check'и: они раскрывают внутреннюю топологию, а обзор
отдаёт (замаскированные) пароли инфраструктуры. Ответы идут с
`Cache-Control: no-store`.

| Method | Path | Notes |
|---|---|---|
| GET  | `/infrastructure/` | Обзор; секреты замаскированы |
| POST | `/infrastructure/credentials/reveal` | Раскрыть секреты по паролю админа. `admin=True` проверяется ВРУЧНУЮ, а не декоратором: гейт ответил бы 403 раньше, чем сработал бы rate-limit, а это единственный роут, куда подбирают пароль. Порядок: админство → лимит → пароль |
| GET  | `/infrastructure/audit/reveals` | Журнал раскрытий |
| GET  | `/infrastructure/health-check` | Проверить всё |
| GET  | `/infrastructure/health-history` | История проверок |
| POST | `/infrastructure/<resource_id>/health-check` | Проверить один ресурс |
| GET  | `/infrastructure/targets` | Состояние скрейп-таргетов Prometheus |

Каждый путь зарегистрирован в двух написаниях — со слешем и без
(`APPEND_SLASH = False`), потому что фронт зовёт их и так, и так.

⚠️ **`/infrastructure/targets` существует именно потому, что `/prometheus/` наружу
НЕ проксируется.** У Prometheus нет собственной авторизации, поэтому открытый
`location` отдал бы его UI и API любому. Виджет мониторинга раньше ходил прямо в
`/prometheus/api/v1/targets` и работал только под dev-прокси Vite, а в проде
показывал ошибку всегда. Теперь запрос делает сервер по внутренней сети, а
наружу он закрыт тем же admin-гейтом. Ответ — `{"targets": [...]}` с полями
`labels`, `health`, `lastScrape`, `lastScrapeDuration`, `lastError`;
`discoveredLabels` из ответа Prometheus вырезаны — это внутренняя топология.
Недоступный Prometheus даёт **503**, а не 500: это отказ соседа, а не ошибка
платформы.

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
