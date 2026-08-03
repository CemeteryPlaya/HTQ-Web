# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Migration history (done)

The FastAPI→Django reverse migration — built by **two parallel executors** (Поток A = `hr`/`mail`/`messenger`, Поток B = `tasks`/`approvals`; see **[PLAN.md](PLAN.md)** for the full phase-by-phase journal) — is **complete and cut over**: all 9 FastAPI microservices and `libs/` (`htqweb_auth`, `htqweb_metrics`) were deleted from the repo, and the platform now runs as **one Django backend** (`backend/`). If you see "Поток A"/"Поток B" or "PLAN.md §..." in code comments, that's just where a piece of code came from — the zone split no longer restricts anything; work across any `backend/apps/**` as directed.

- **Cross-app access is still ONLY via `apps.<x>.interface`** (enforced by `apps/core/tests/test_app_isolation.py`) — no direct imports of another app's models/services, no cross-domain FK. That invariant survived the migration unchanged.
- **NEVER create git branches yourself.** The user creates and hands off every branch. Do not run `git branch`, `git checkout -b`, `git switch -c`, or `git worktree add`, and do **not** "branch first" before committing — even on the default branch. This overrides the default Claude Code behavior. Work only on the branch you are given; if the expected branch seems missing or wrong, stop and ask.

## What this is

HTQWeb — Hi-Tech Group's internal enterprise platform. A React + Vite SPA in front of **one Django backend** (Python 3.14, Django 5.2.7). Postgres (direct connection, app-level pooling), Redis (cache + Celery broker), MinIO/S3 object storage, Mediasoup SFU for video.

For context, the platform's history is a full circle: it started as a Django monolith, was migrated (Strangler Fig) out to ~9 FastAPI microservices behind an nginx gateway, and has now been merged back into a single Django backend (the reverse migration above). MongoDB (previously HR docs + the old admin panel) is gone along with the FastAPI generation.

## Read these first (don't re-derive the layout)

These are authoritative and maintained — prefer them over scanning the tree:
- **[STRUCTURE.md](STRUCTURE.md)** — the navigation map: every directory, the Django-app anatomy, where each concern lives. Russian.
- **[API.md](API.md)** — the full nginx routing table (`/api/<domain>/v1/*`), auth/JWT contract, per-domain endpoints.
- **[backend/README.md](backend/README.md)** — Django app anatomy, `interface`/`api_view` rules, how to add a domain. Replaces the deleted `services/README.md`.
- **[docs/architecture.md](docs/architecture.md)** — architectural decisions (predates the cutover in places — e.g. it still talks about DRF ViewSets and a `backend/tasks/` layout that doesn't exist; treat it as background, not a source of truth for current layout).

Ignore/discount at the repo root: empty `nginx/`, root `node_modules/`+`package.json` (tooling only). **`docker-compose.django.yml` and `RUN-DJANGO-CHECK.md` describe an earlier, now-superseded proof-of-concept stack** (a parallel `htqweb-django` project from when only `users`/`cms`/`media`/`hr` were ported and everything else was an empty app) — superseded by `docker-compose.yml` + `docker-compose.dev.yml`, which reflect the completed cutover. The only authoritative gateway config is `infra/nginx/default.conf`.

## Commands

Containers are named `htq-web-<service>-1` (e.g. `htq-web-backend-web-1`, `htq-web-db-1`, `htq-web-pgbouncer-1`) — the compose project takes its name from the repo directory.

**Run the stack (dev — Vite HMR on :3000, MinIO, DEBUG settings):**
```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
# rebuild + recreate one process after code changes:
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build --no-deps backend-web
```
Prod stack is plain `docker compose up -d` (adds nginx/certbot under the `production` profile).

**Конференция (SFU) поднята и в dev, и в проде.** `sfu` (mediasoup, сигналинг `:4443`, медиа `:44444/udp+tcp`) и `webtransport` (QUIC-мост `:4433/udp`) больше не под профилем `production` — стартуют вместе со стеком. Что важно знать:
- **Сигналинг требует платформенный JWT.** SFU валидирует токен на WS-upgrade тем же `JWT_SECRET`/HS256, что и Django (`sfu/src/auth.ts`); браузер передаёт его подпротоколом `['htqweb.jwt', <token>]`, WebTransport-мост — параметром `?token=`. Без токена — 401 на upgrade. Отключается только для локальной отладки: `SFU_REQUIRE_AUTH=false`.
- **`WEBRTC_ANNOUNCED_IP` обязателен.** С wildcard listenIp и пустым announced SFU падает на старте намеренно (иначе — чёрное видео). В dev подставляется `127.0.0.1` (браузер на той же машине); для проверки с другого устройства поставьте LAN-IP хоста в корневом `.env`, в проде — публичный IP.
- **Транспорт сигналинга:** фронт сначала пробует WebTransport (QUIC), при неудаче сам откатывается на WebSocket (`WebRTCManager.buildSignalingAttempts`). Адрес моста и отпечаток его самоподписанного сертификата приезжают в `GET /api/cms/v1/conference/config` (`wt_signaling_url` / `wt_certificate_hashes`).
- Флаг сервиса в реестре включён миграцией `core/0003_enable_conference`; на боевой БД с `RUN_MIGRATIONS=0` её нужно применить руками (`manage.py migrate core`) либо флипнуть `manage.py service conference --on`.

**Frontend** (`cd frontend`):
```bash
npm run dev            # vite dev server :3000
npm run build          # vite build (+ bundle-size budget check in postbuild)
npm run lint           # eslint
npx tsc --noEmit -p tsconfig.json   # typecheck (use this to verify changes)
npm test               # vitest run
npx vitest run <file> -t "<name>"   # single test
npm run test:e2e       # playwright
```
Playwright: the chromium binary isn't installed; launch with `{ channel: 'msedge' }` (Edge ships on the Windows host).

**Backend tests** (`cd backend`): pytest-django against **real Postgres** (no SQLite), on a dedicated host port because neither existing route works (`:5432` is a native Windows Postgres install, `:6432`/PgBouncer is transaction-pooled and can't `CREATE DATABASE`). Bring the port up once, then run the suite:
```bash
docker compose -f docker-compose.yml -f docker-compose.test.yml up -d db   # publishes db on :55432
cd backend
../.venv/Scripts/python.exe -m pytest -q                                   # whole suite
../.venv/Scripts/python.exe -m pytest apps/hr/tests/test_x.py::test_name   # single test
```
`DJANGO_SETTINGS_MODULE=htqweb.settings.test` and `JWT_SECRET` are both fixed by `pytest.ini`/`settings/test.py` — nothing to export by hand. Full detail (including the `max_connections=300` bump): [backend/README-tests.md](backend/README-tests.md).

**Django management** (`cd backend`, same venv):
```bash
../.venv/Scripts/python.exe manage.py makemigrations <app>   # after model changes
../.venv/Scripts/python.exe manage.py migrate
../.venv/Scripts/python.exe manage.py service <name> --on|--off [--message "..."]   # ServiceStatus switch
../.venv/Scripts/python.exe manage.py etl_<domain> [--dry-run] [--verify] [--limit N]  # phase-10 legacy-data cutover
../.venv/Scripts/python.exe manage.py seed_tasks_demo [--purge|--wipe|--wipe-only]  # demo data, local DB only
```
`seed_tasks_demo` fills the whole five-level hierarchy (project → site → block → roadmap → task) plus volumes, resource requirements and dated daily reports; it needs `seed_hr_demo` to have run first (it reads departments/employees through `apps.hr.interface`). `--purge` removes only what it seeded, `--wipe` TRUNCATEs every table of the `tasks` app and re-seeds — including restoring the five system `TaskType` rows that migration `0002` had put there.

**Reaching the dev database from the host**: `manage.py` defaults to `localhost:6432` (PgBouncer), whose credentials fail SASL from the host. Use the unpooled port instead — same server, dev database:
```bash
cd backend
DJANGO_SETTINGS_MODULE=htqweb.settings.dev DB_HOST=localhost DB_PORT=55432 \
  DB_NAME=htqweb DB_USER=htqweb DB_PASSWORD=change-me JWT_SECRET=dev PYTHONIOENCODING=utf-8 \
  ../.venv/Scripts/python.exe manage.py <command>
```
(`:55432` comes up with `docker compose -f docker-compose.yml -f docker-compose.test.yml up -d db`. `PYTHONIOENCODING=utf-8` is needed or Russian output comes out mojibake on the Windows console.)

## Architecture invariants (the load-bearing ones)

- **One Django backend, domains are apps.** `backend/apps/{users,cms,media_files,hr,mail,messenger,tasks,approvals,contracts,signoff,core}`. Two of those post-date the migration and have no FastAPI ancestor: **`contracts`** (`/api/contracts/v1`, budgets/counterparties/agreements) and **`signoff`** (`/api/signoff/v1`, generic multi-stage approval over *other apps'* rows — **not** `apps.approvals`, which is a form designer approving its own `RequestInstance`s; see STRUCTURE.md §3.6). `apps.core` is the only shared foundation (JWT/service-registry primitives live in `htqweb/`, not in an app); every other app talks to a neighbour ONLY through that neighbour's `apps.<x>.interface` module — never its `models`/`services` directly (enforced by the isolation test above).
- **API layer is hand-rolled Django, not DRF.** `htqweb.http.api_view` (`methods=`, `auth="jwt"|"admin_session"|None`, optional Pydantic `body=`, `admin=True` gate) decorates views; the error envelope is always `{"detail": ...}` (401/403/404/422/500/503), matching the old FastAPI contract. Pydantic schemas (`apps/<domain>/schemas.py`) carried over from the FastAPI services essentially as-is and still do request/response validation.
- **URLs auto-mount by convention.** An app declares `API_PREFIX = "api/<domain>/v1/"` on its `AppConfig` (`apps/<domain>/apps.py`) and defines `apps/<domain>/urls.py`; `htqweb/urls.py` discovers every installed app with that attribute and mounts it — adding a domain never touches `htqweb/urls.py`. `APPEND_SLASH = False`, so `urls.py` registers both the slashed and bare spelling of a path wherever the frontend might send either.
- **Business logic lives in `apps/<domain>/services/<file>.py`.** `views.py` are thin dispatchers (parse → call service → shape response). Look in `services/`, not in views, for behavior.
- **JWT issuer is still `htqweb-auth`.** There's no separate user-service anymore — `apps.users` both issues (`htqweb/authn/jwt.py`, called from `apps.users.views`) and every app validates tokens locally via the same shared `JWT_SECRET`/HS256, in-process, no network call. Claims are unchanged: `sub, user_id, username, email, is_staff, is_superuser, is_admin, token_type, iat, exp, iss`.
- **Apps are disableable at runtime**, same mechanism as before the merge, just in-process now: `apps.core.models.ServiceStatus` (one DB row per domain, 5s-cached) + `htqweb.middleware.service_gate.ServiceGateMiddleware` (gates `/api/<prefix>/` and `/ws/.../` by URL prefix) + `apps.core.services.require_service("<name>")` (the in-process gate — first line of every `interface.py` function and every Celery task) + `htqweb.admin_gate.ServiceGatedAdminMixin` (gates that app's models in `/django-admin/`). Flip one with `manage.py service <name> --on/--off`. A disabled dependency surfaces as 503 `{"detail", "code": "service_disabled", "service"}` everywhere — HTTP edge, an in-process `interface` call turned into `ServiceDisabled`, or `django-admin` (which fails the Django-native way: `PermissionDenied`, not a JSON body).
- **Processes** (`docker-compose.yml`, all built from the same `backend/Dockerfile` image, differing only in `command`): `backend-web` (gunicorn/WSGI — all of `/api/*`, `/django-admin/`, static; the **only** process that runs `migrate` + seeds the `admin`/`admin12345` account, gated by `RUN_MIGRATIONS=1`), `backend-asgi` (uvicorn/ASGI — SSE `/api/requests/v1/stream` + WebSocket `/ws/`; messenger's Socket.IO mounts at `ws/messenger/socket.io`), `backend-worker` (Celery), `backend-beat` (Celery beat, `django-celery-beat` DB-backed scheduler), `flower` (Celery monitoring UI). Broker/result backend is Redis. Every Celery task's first line is `require_service("<app>")`.
- **nginx (`infra/nginx/default.conf`) is the gateway**: two upstreams, `backend` (WSGI, everything else) and `backend_asgi` (the SSE route + `/ws/`). In dev, Vite's proxy (`frontend/vite.config.ts`) mirrors that split — every `*ServiceTarget` variable it defines now resolves to the same `VITE_BACKEND_TARGET` (the per-service names only survive because the proxy rule table still keys off them).

## Postgres — direct connection now; PgBouncer is legacy-shaped history

- **Django talks straight to Postgres**: `DB_HOST=db`, `DB_PORT=5432` (psycopg, sync), `CONN_MAX_AGE=0` — pooling is app-level, not a shared external pooler. PgBouncer (`:6432`) is still in the compose file for host-side tooling/manual `psql`, but it is **not** in the live request path anymore.
- **History (no longer applies — here so old scars make sense if you trip over them):** the FastAPI generation put every service behind PgBouncer in transaction-pooling mode, which silently drops `search_path`, so all 8 Python services (except `user`→schema `auth`) actually lived in schema `public` with a table-name-prefix convention (`hr_*`, `task_*`, `request_*`, `cms_*`, `email_*`), and Alembic needed a fresh-thread-per-migration dance to survive the pooler. None of that applies to Django: one schema (`public`), natural table names (`<app>_<model>`), `managed=True`, plain `makemigrations`/`migrate`.
- **Tests need a real, unpooled Postgres** — `CREATE DATABASE`/`DROP DATABASE test_htqweb` cannot pass through PgBouncer's transaction pool. That's what host port `:55432` (`docker-compose.test.yml`) is for; see [backend/README-tests.md](backend/README-tests.md).

## Host / Windows environment notes

- Shell is PowerShell 5.1; a Bash tool (Git Bash) is also available. **PowerShell mangles `$`, inner quotes, and JSON** in `docker exec`/`psql` args — route anything with `$`, quotes, or JSON bodies through the Bash tool.
- From the Windows host: **`:6432`** reaches the project DB through PgBouncer (host tooling/manual queries only); **`:55432`** is the direct, unpooled Postgres the test suite uses; host **`:5432`** is a native Windows PostgreSQL install, not the container.
- `DB_NAME=htqweb`, `DB_USER=htqweb`, dev password `change-me` (root `.env`).

## Observability

Prometheus (`:9090/prometheus`) currently scrapes itself + `postgres-exporter`, `redis-exporter`, MinIO, and Loki/Grafana (6 targets total, `infra/logging/prometheus/prometheus.yml`) — **the Django backend does not expose `/metrics` yet**: the old `htqweb_metrics` lib was deleted with the FastAPI services, and a `django-backend` scrape job is pre-written in that file but left commented out pending a `django-prometheus` install. Grafana (`:3001`, or `/grafana/` via the edge) keeps its JWT SSO: platform accounts sign in with their access token (superuser→Admin, staff→Editor); dashboards live in the **HTQWeb** folder. Config in `infra/logging/`. `scripts/generate-monitoring-traffic.sh` predates the cutover and still hardcodes the old per-service ports (`:8005`-`:8012`) — it needs a rewrite before it'll generate any real traffic against this backend.
