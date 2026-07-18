# API Documentation — HTQWeb Platform

> **State as of `0.1.2` (Phase 5 complete).** Django removed; 8 FastAPI
> microservices behind a Vite dev proxy (`:3000`) or nginx prod gateway
> (`:80`). Real-time chat over Socket.IO. Per-service Postgres schemas.

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
│ Microservices (Docker network — not directly user-reachable in prod) │
│                                                                       │
│   user-service       :8005   /api/users/v1/*                         │
│   hr-service         :8006   /api/hr/v1/*                            │
│   task-service       :8007   /api/tasks/v1/*                         │
│   messenger-service  :8008   /api/messenger/v1/*  +  Socket.IO       │
│   media-service      :8009   /api/media/v1/*                         │
│   email-service      :8010   /api/email/v1/*                         │
│   cms-service        :8011   /api/cms/v1/*                           │
│   admin-service      :8012   /sqladmin/*                             │
│                                                                       │
│   user-worker, user-scheduler, hr-worker, ... (Dramatiq + APScheduler)│
└──────────────────────────────────────────────────────────────────────┘
          │
          ▼
┌──────────────────────────────────────────────────────────────────────┐
│ Postgres :5432                                                        │
│   schemas: auth, hr, tasks, cms, media, messenger, email             │
│   PgBouncer :6432 (transaction pooling)                              │
│ Redis :6379  (Dramatiq broker, Socket.IO adapter, pub/sub)           │
│ Loki :3100, Grafana :3001                                            │
└──────────────────────────────────────────────────────────────────────┘
```

## Access URLs (dev mode — `docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d`)

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

> ⚠️ **`{"detail":"Not Found"}` from microservices** typically means the
> request is missing its service prefix. Use the routing table below — every
> canonical prefix is `/api/<service>/v1/...`.

## Production access (nginx :80)

`docker compose up -d` (without `-f docker-compose.dev.yml`) brings up
nginx on `:80`. Same routing table, but the Vite dev server isn't running.

---

## Routing table

| Prefix                              | Service           | Notes                                        |
|-------------------------------------|-------------------|----------------------------------------------|
| `/`, `/login`, `/register`, `/admin/users`, `/admin/chats`, … | Frontend SPA  | All other paths fall through to React Router |
| `/api/users/v1/*`                   | user-service      | Auth, profile, registrations, items, admin   |
| `/api/hr/v1/*`                      | hr-service        | Employees, departments, vacancies, time      |
| `/api/tasks/v1/*`                   | task-service      | Tasks, calendar, sequences, attachments      |
| `/api/messenger/v1/*`               | messenger-service | Rooms, messages, keys (E2EE), attachments    |
| `/api/media/v1/files/*`             | media-service     | Uploads, downloads with Range, thumbnails    |
| `/api/email/v1/*`                   | email-service     | OAuth (Google/Microsoft), SMTP/IMAP, DLP     |
| `/api/cms/v1/news/*`                | cms-service       | News articles                                |
| `/api/cms/v1/contact-requests/*`    | cms-service       | Public contact form + admin queue            |
| `/api/cms/v1/conference/config`     | cms-service       | SFU/WebRTC runtime config                    |
| `/sqladmin/*`                       | admin-service     | sqladmin DB dashboard (NOT the SPA admin)    |
| `/ws/messenger/socket.io/*`         | messenger-service | Real-time chat (Socket.IO)                   |
| `/ws/sfu/*`                         | sfu (mediasoup)   | WebRTC signalling for /conference            |

### Temporary compatibility aliases

Vite dev/preview and nginx rewrite cached old frontend paths to canonical
service prefixes. Examples:

| Old path | Canonical path |
|----------|----------------|
| `/api/token/*`, `/api/register/*`, `/api/items/*` | `/api/users/v1/...` |
| `/api/v1/profile/*`, `/api/pending-registrations/*` | `/api/users/v1/...` |
| `/api/news/*`, `/api/contact-requests/*`, `/api/v1/contact-requests/*` | `/api/cms/v1/...` |
| `/api/calendar-events/*` | `/api/tasks/v1/calendar/...` |
| `/api/calendar-timeline/*` | `/api/tasks/v1/calendar/timeline/...` |
| `/api/media/v1/{not files}/*` | `/api/media/v1/files/...` |
| `/api/users/*`, `/api/hr/*`, `/api/tasks/*`, `/api/cms/*`, `/api/email/*`, `/api/messenger/*` without `/v1/` | matching `/api/<service>/v1/...` |

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

JWT claims (HS256 with `JWT_SECRET`, issuer `htqweb-auth`):
```
{ user_id, username, email, is_staff, is_superuser, is_admin,
  token_type: "access" | "refresh", iat, exp, iss }
```
`is_admin = is_staff OR is_superuser`. All microservices validate JWTs
locally — no introspection round-trip.

### Refresh token

```
POST /api/users/v1/token/refresh/
Content-Type: application/json

{ "refresh": "<jwt>" }
→ 200 { "access": "<jwt>", "token_type": "Bearer" }
```

### Admin-session cookie (sqladmin login)

```
POST /api/users/v1/admin-session/login
Content-Type: application/x-www-form-urlencoded

username=admin&password=...&next=/sqladmin/
→ 303 Set-Cookie: admin_session=<jwt>; HttpOnly; SameSite=Lax; Path=/
       Location: /sqladmin/
```
The cookie is recognised by every service's sqladmin backend
(`JWTAdminAuthBackend`); a single login lights up DB admin across the platform.

```
POST /api/users/v1/admin-session/logout   →   { "ok": true } + clears cookie
```

### Bootstrap an admin user

```
docker compose exec user-service \
  python -m app.scripts.create_admin \
    --username admin --email admin@htqweb.local --password admin123 \
    --first-name Admin --last-name Root
```
Creates or upgrades the user to `status=ACTIVE`, `is_staff=is_superuser=True`.

---

## user-service `/api/users/v1`

### Profile

```
GET  /api/users/v1/profile/me        → ProfileResponse
GET  /api/users/v1/profile/          → ProfileResponse (alias)
PATCH /api/users/v1/profile/me       multipart/form-data → ProfileResponse
PATCH /api/users/v1/profile/         multipart/form-data → ProfileResponse
POST /api/users/v1/profile/change-password  { current_password?, new_password }
```
PATCH body fields: `display_name`, `firstName`/`first_name`, `lastName`/
`last_name`, `patronymic`, `bio`, `phone`, `settings` (JSON string), and
optional `avatar` (UploadFile — forwarded to media-service via S2S JWT).

### Registration

```
POST /api/users/v1/register/                          { email, password, full_name }
GET  /api/users/v1/pending-registrations/             admin only
POST /api/users/v1/pending-registrations/{id}/approve/  → 204, publishes user.upserted
POST /api/users/v1/pending-registrations/{id}/reject/   → 204, publishes user.deactivated
```

### Admin user management

```
GET  /api/users/v1/admin/users/                       admin only
PATCH /api/users/v1/admin/users/{id}/                 admin only, publishes user.upserted/deactivated
```

### Items (personal notes)

```
GET    /api/users/v1/items/
POST   /api/users/v1/items/                           { title, description }
GET    /api/users/v1/items/{id}/
PATCH  /api/users/v1/items/{id}/
DELETE /api/users/v1/items/{id}/
```

### Client-side error/event ingestion

```
POST /api/users/v1/client-errors/                     { message, stack, url, user_agent, ... }
POST /api/users/v1/client-events/                     { event, payload, ... }
```

---

## hr-service `/api/hr/v1`

| Endpoint                                  | Method | Notes                          |
|-------------------------------------------|--------|--------------------------------|
| `/api/hr/v1/employees/`                   | GET, POST | Employee CRUD               |
| `/api/hr/v1/employees/{id}/`              | GET, PATCH, DELETE |                       |
| `/api/hr/v1/departments/`                 | GET, POST | Tree (`ltree path`)         |
| `/api/hr/v1/positions/`                   | GET, POST |                              |
| `/api/hr/v1/vacancies/`                   | GET, POST |                              |
| `/api/hr/v1/applications/`                | GET, POST | Candidate applications      |
| `/api/hr/v1/time/`                        | GET, POST | Time tracking               |
| `/api/hr/v1/documents/`                   | GET, POST | HR documents                |
| `/api/hr/v1/department-folders/`          | GET    | Department folders visible to current user |
| `/api/hr/v1/department-file-folders/`     | GET, POST | User-created folders inside a department |
| `/api/hr/v1/department-files/`            | GET, POST | Department-scoped files; POST forwards bytes to media-service |
| `/api/hr/v1/department-files/{id}/`       | DELETE | Remove HR metadata for a department file |
| `/api/hr/v1/audit/`                       | GET    | Read-only audit log            |
| `/api/hr/v1/org/`                         | GET    | Organisational settings        |
| `/api/hr/v1/pmo/`                         | GET, POST | Project management office   |
| `/api/hr/v1/share-links/`                 | GET, POST |                              |
| `/api/hr/v1/public/org/{token}`           | GET    | Public org-chart by share link |

---

## task-service `/api/tasks/v1`

| Endpoint                                          | Method | Notes                       |
|---------------------------------------------------|--------|-----------------------------|
| `/api/tasks/v1/tasks/`                            | GET, POST | List + create            |
| `/api/tasks/v1/tasks/{id}/`                       | GET, PATCH, DELETE |                  |
| `/api/tasks/v1/tasks/{id}/comments/`              | GET, POST |                           |
| `/api/tasks/v1/tasks/{id}/attachments/`           | GET, POST |                           |
| `/api/tasks/v1/tasks/{id}/activity/`              | GET    | Activity log                 |
| `/api/tasks/v1/tasks/{id}/links/`                 | GET, POST | Cross-task links          |
| `/api/tasks/v1/labels/`                           | GET, POST |                           |
| `/api/tasks/v1/versions/`                         | GET, POST | Project versions          |
| `/api/tasks/v1/calendar/`                         | GET, POST | Calendar events           |
| `/api/tasks/v1/calendar/{id}/`                    | PATCH, DELETE | Calendar event         |
| `/api/tasks/v1/calendar/{id}/exceptions/`         | POST   | Calendar event exception      |
| `/api/tasks/v1/calendar/timeline/`                | GET    | `{ tasks, events }` by `start`/`end` |
| `/api/tasks/v1/production-calendar/`              | GET, PATCH | Production days, Kazakhstan holidays |
| `/api/tasks/v1/sequences/`                        | GET    | Atomic key generators        |
| `/api/tasks/v1/notifications/`                    | GET    |                              |

---

## messenger-service `/api/messenger/v1` + Socket.IO

### REST

| Endpoint                                                | Method | Notes                            |
|---------------------------------------------------------|--------|----------------------------------|
| `/api/messenger/v1/rooms/`                              | GET, POST | Create/list rooms             |
| `/api/messenger/v1/rooms/{id}`                          | GET, DELETE |                               |
| `/api/messenger/v1/messages/`                           | POST   | Send message → emits `message_new` |
| `/api/messenger/v1/messages/room/{id}`                  | GET    | Paginated history                 |
| `/api/messenger/v1/messages/room/{id}/read/{msg_id}`    | POST   | → emits `message_read`            |
| `/api/messenger/v1/messages/room/{id}/typing`           | POST   | → emits `user_typing`             |
| `/api/messenger/v1/keys/`                               | POST   | Upload E2EE pre-key bundle       |
| `/api/messenger/v1/keys/{user_id}`                      | GET    | Fetch peer's pre-keys             |
| `/api/messenger/v1/users/ingest`                        | POST   | Internal: replicate user from user-service |
| `/api/messenger/v1/attachments/upload`                  | POST   | Multipart upload                  |
| `/api/messenger/v1/admin/rooms`                         | GET    | Admin: all rooms                 |
| `/api/messenger/v1/admin/rooms/{id}/messages`           | GET    | Admin: full history               |

### Socket.IO

```
URL:  ws://<host>:3000/ws/messenger/socket.io/
Auth: { token: "<JWT>" }   (also accepted as ?token=… or Authorization: Bearer …)
```

**Server → Client events:**

| Event           | Payload                                                      |
|-----------------|--------------------------------------------------------------|
| `message_new`   | `{ room_id, message: {...} }`                                |
| `message_read`  | `{ room_id, message_id, reader_user_id }`                    |
| `user_typing`   | `{ room_id, user_id, is_typing }`                            |

**Client → Server events:**

| Event       | Payload                       | ack                                         |
|-------------|-------------------------------|---------------------------------------------|
| `join_room` | `{ room_id }`                 | `{ ok: true }` or `{ ok: false, error: "not_a_member" }` |
| `leave_room`| `{ room_id }`                 | `{ ok: true }`                              |
| `typing`    | `{ room_id, is_typing }`      | —                                            |
| `mark_read` | `{ room_id, message_id }`     | — (also persists `last_read_message_id`)    |

---

## media-service `/api/media/v1`

| Endpoint                          | Method | Notes                                   |
|-----------------------------------|--------|-----------------------------------------|
| `/api/media/v1/files/`            | POST   | multipart upload → `{ id, url, mime }`  |
| `/api/media/v1/files/{path:path}` | GET    | Download with HTTP Range, ETag, 8K chunks |

S2S uploads (e.g. avatar from user-service) authenticate with a JWT signed
by `SERVICE_JWT_SECRET` and an `X-User-Id` header.

---

## email-service `/api/email/v1`

| Endpoint                                  | Method | Notes                            |
|-------------------------------------------|--------|----------------------------------|
| `/api/email/v1/inbox`                     | GET    |                                  |
| `/api/email/v1/sent`                      | GET    |                                  |
| `/api/email/v1/drafts`                    | GET, POST |                               |
| `/api/email/v1/trash`                     | GET    |                                  |
| `/api/email/v1/send`                      | POST   | Enqueues `send_email` actor      |
| `/api/email/v1/read/{id}`                 | GET    |                                  |
| `/api/email/v1/oauth/init`                | POST   | Google / Microsoft OAuth start   |
| `/api/email/v1/oauth/callback`            | GET    |                                  |
| `/api/email/v1/oauth/status`              | GET    |                                  |
| `/api/email/v1/oauth/disconnect`          | POST   |                                  |

---

## cms-service `/api/cms/v1`

| Endpoint                                       | Method | Notes                              |
|------------------------------------------------|--------|------------------------------------|
| `/api/cms/v1/news/`                            | GET, POST | Public list + admin create     |
| `/api/cms/v1/news/{id}`                        | GET, PATCH, DELETE |                          |
| `/api/cms/v1/news/{id}/translate`              | POST   | Enqueues translation actor      |
| `/api/cms/v1/contact-requests/`                | POST   | **Public**, rate-limited (3/min) |
| `/api/cms/v1/contact-requests/`                | GET    | Admin queue                       |
| `/api/cms/v1/contact-requests/stats`           | GET    | `{ total, unread, ... }`          |
| `/api/cms/v1/contact-requests/{id}`            | GET, PATCH, DELETE |                          |
| `/api/cms/v1/contact-requests/{id}/reply`      | POST   |                                    |
| `/api/cms/v1/conference/config`                | GET    | SFU runtime config (no DB)        |

---

## sqladmin (admin-service) `/sqladmin`

Browser-based DB dashboard. Protected by the `admin_session` cookie issued by
`POST /api/users/v1/admin-session/login`. Mounted at **`/sqladmin/`** so it
doesn't collide with the SPA's own `/admin/users`, `/admin/chats`, and
`/admin/registrations` React pages.

```
GET /sqladmin/        → 302 /sqladmin/login if no cookie, else 200 dashboard
GET /sqladmin/login   → login form (POSTs to user-service)
```

The aggregator service mounts **every microservice's ModelViews** under one
sqladmin instance (it imports models from all 7 service packages via
PYTHONPATH volumes; see `services/admin/Dockerfile`).

---

## Health checks

Every service answers:

```
GET /health/         → 200 {"status":"ok","service":"<name>","timestamp":"..."}
GET /health/ready/   → 200 (or 503 if its own DB/Redis are not reachable)
```

The Vite dev proxy doesn't expose `/health/` directly — hit each service on
its host port (`8005`–`8012`) for a liveness check. nginx in production
exposes the gateway-level `/health` and `/health/ready`.

---

## Cross-service contract

| Concern              | Rule                                                              |
|----------------------|-------------------------------------------------------------------|
| **HTTP API**         | Each service binds `0.0.0.0:<port>`. All HTTP errors use FastAPI's default `{"detail": "..."}` envelope; client-side parsers should read `detail`. |
| **Health**           | `/health/` (liveness) + `/health/ready/` (readiness, checks DB).  |
| **Request ID**       | Gateway emits `X-Request-ID`; services log it via `RequestIDMiddleware` and propagate to downstream calls. |
| **JWT validation**   | Every service decodes the JWT locally with the shared `JWT_SECRET` (HS256). No introspection. |
| **User context**     | `payload.user_id` (int) is the source of truth.                   |
| **Authorisation**    | `is_staff` / `is_superuser` / `is_admin` claims gate admin paths. |
| **Service-to-service** | When a service calls another, it issues an S2S JWT (`SERVICE_JWT_SECRET` claim `sub: "<service-name>"`) and adds `X-User-Id` for audit. |
| **Logging**          | structlog → JSON to stdout → Promtail → Loki. Every record includes `service`, `correlation_id` (= request id when available). |
| **Database**         | Each service uses its own schema (`auth, hr, tasks, cms, media, messenger, email`). Connection through `pgbouncer:5432`, transaction pooling, `IGNORE_STARTUP_PARAMETERS=search_path`. |
| **Migrations**       | `alembic upgrade head` runs at container start (`entrypoint.sh`). Per-service `alembic_version_<svc>` table in the service's schema. |
| **Pub/Sub**          | Redis channels: `user.upserted`, `user.deactivated` (replica fan-out from user-service to messenger + task). |
| **Worker queue**     | Dramatiq with Redis broker. One `<svc>-worker` and `<svc>-scheduler` container per service. |

---

## Rate limiting (nginx prod only)

| Zone               | Limit       | Burst |
|--------------------|-------------|-------|
| `api_auth`         | 5 req/min   | 2     |
| `api_general`      | 30 req/s    | 20    |
| `api_public`       | 10 req/min  | 5     |
| `websocket`        | 10 req/s    | 5     |

Vite dev proxy doesn't enforce rate limits.

---

## Error responses

FastAPI's default envelope, plus the standard HTTP status meaning:

```json
{ "detail": "human-readable message" }
```

| Status | Meaning                                                           |
|--------|-------------------------------------------------------------------|
| 400    | Validation / malformed request                                    |
| 401    | Missing or invalid JWT                                            |
| 403    | Authenticated but not authorised (e.g. non-admin on admin route)  |
| 404    | Resource (or route) not found — see the routing table above       |
| 409    | Conflict (e.g. duplicate email on register)                       |
| 422    | Pydantic validation error (FastAPI built-in)                       |
| 429    | Rate limit exceeded (nginx prod only)                             |
| 500    | Unhandled service exception                                       |
| 502/503| Upstream service unhealthy                                        |

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
