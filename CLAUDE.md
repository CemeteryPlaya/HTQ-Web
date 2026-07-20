# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Dual Django migration — this working branch is Поток A

The FastAPI→Django reverse migration is being finished by **two parallel executors** — see **[PLAN.md](PLAN.md)** (authoritative). **This branch is Поток A.** Its scope is **only**: `backend/apps/hr/**`, `backend/apps/mail/**`, `backend/apps/messenger/**` (+ append-only edits to `backend/requirements.txt`, + its own Socket.IO section of `htqweb/asgi.py`). Поток A **produces** the `hr`/`mail`/`messenger` interfaces and depends only on the finished `users`.

- **Do NOT touch Поток B's zone:** `backend/apps/tasks/**`, `backend/apps/approvals/**`, and the prep-owned shared files (`htqweb/urls.py`, `INSTALLED_APPS`, `service_gate.py`, `apps/core/tests/test_invariants.py`, the `asgi.py` scaffold). Need cross-domain data → call the neighbour's `interface` stub; never implement another domain (PLAN.md §1.3, §1.5).
- **NEVER create git branches yourself.** The user creates and hands off every branch. Do not run `git branch`, `git checkout -b`, `git switch -c`, or `git worktree add`, and do **not** "branch first" before committing — even on the default branch. This overrides the default Claude Code behavior. Work only on the branch you are given; if the expected branch seems missing or wrong, stop and ask.

## What this is

HTQWeb — Hi-Tech Group's internal enterprise platform. A React + Vite SPA in front of ~9 FastAPI microservices behind an nginx API gateway, migrated (Strangler Fig) out of a now-removed Django monolith. Postgres (via PgBouncer), MongoDB (HR docs + admin panel), Redis (cache + Dramatiq broker + pub/sub), Mediasoup SFU for video.

## Read these first (don't re-derive the layout)

These are authoritative and maintained — prefer them over scanning the tree:
- **[STRUCTURE.md](STRUCTURE.md)** — the navigation map: every directory, the per-service anatomy, where each concern lives. Trustworthy (corrected 2026-05-29). Russian.
- **[API.md](API.md)** — the full nginx routing table (`/api/<service>/v1/*`), auth/JWT contract, per-service endpoints.
- **[services/README.md](services/README.md)** — microservice anatomy and the shared-code rules.
- **[docs/architecture.md](docs/architecture.md)** — architectural decisions.

Ignore at the repo root: `backend/` (dead Django remnant, untracked), empty `nginx/`, root `node_modules/`+`package.json` (tooling only). The only authoritative gateway config is `infra/nginx/default.conf`.

## Commands

Containers are named `htqweb1-<service>-1` (e.g. `htqweb1-user-service-1`, `htqweb1-db-1`, `htqweb1-pgbouncer-1`).

**Run the stack (dev — Vite HMR on :3000, MinIO, `/docs` enabled):**
```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
# rebuild + recreate one service after code changes:
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build --no-deps <name>-service
```
Prod stack is plain `docker compose up -d` (adds nginx/sfu/certbot under the `production` profile).

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

**Backend tests** (per service, `cd services/<name>`): pytest with `asyncio_mode = "auto"`; tests use in-memory SQLite (no Postgres needed). `JWT_SECRET` must be in the env *before* app import — conftest sets it.
```bash
pytest                                          # whole service
pytest tests/integration/test_x.py::test_name   # single test
```

## Architecture invariants (the load-bearing ones)

- **One service = one isolated FastAPI app** cloned from `services/_template/` (`python services/scaffold.py <name> "<desc>"`). Web and its Dramatiq worker are the **same Docker image**, different `command` in compose (`uvicorn` vs `dramatiq`).
- **Business logic lives in `app/services/<domain>_service.py`.** Routers in `app/api/v1/` are thin (parse → call service). Look there, not in routers.
- **Only auth is shared** — `libs/htqweb_auth` (JWT/RBAC/levels), on `PYTHONPATH=/app:/app/libs`, re-exported through each service's `app/auth/dependencies.py`. Everything else is **deliberately duplicated** per service, including `s3_storage.py` (change the media copy → propagate to messenger/cms) and `libs/htqweb_metrics` (media keeps its own copy at `app/core/metrics.py`).
- **JWT issuer is `htqweb-auth`** (not `user-service`). user-service signs; every service validates locally with the shared `JWT_SECRET` (HS256) — no introspection call. Tokens carry `sub`, `user_id`, `username`, `email`, `is_staff`, `is_superuser`, `is_admin`.
- **nginx (`infra/nginx/default.conf`) is the gateway**: routes `/api/<service>/v1/*` to each service. In dev, Vite's proxy (`frontend/vite.config.ts`) mirrors that routing instead of nginx.

## Postgres / PgBouncer gotchas (cost real debugging time — internalize these)

- **PgBouncer (transaction mode) silently drops `search_path`.** So a dedicated per-service schema is NOT reachable at runtime. Reality: **all Python services use schema `public` with a table-name prefix** (`hr_*`, `task_*`, `request_*`, `cms_*`, `email_*`); the **only** exception is `user` → schema `auth`. (services/README.md's "one schema per service via search_path" line is the misleading one; STRUCTURE.md §7 is correct.)
- **Migrations run inside the container against Postgres directly** (`DB_HOST=db DB_PORT=5432`, bypassing PgBouncer) — asyncpg's prepared-statement protocol dies on PgBouncer's transaction pool. The entrypoints already do this.
- **One-off scripts** (e.g. `create_admin`) need the direct-DB + real-schema env:
  ```bash
  docker exec -e DB_HOST=db -e DB_PORT=5432 -e DB_SCHEMA=public htqweb1-user-service-1 \
    python -m app.scripts.create_admin --username X --email Y --password Z
  ```
- **Alembic async data-migrations** must: run the coroutine on a fresh-loop thread (`ThreadPoolExecutor(1).submit(asyncio.run, _run()).result()`), `await engine.dispose()` at the end, set `transaction_per_migration=True` in `env.py`, and keep revision ids ≤32 chars (the version column is `VARCHAR(32)`). Reference: `services/hr/alembic/versions/014_backfill_position_perms.py`. Verify a chain single-pass on a scratch DB: `CREATE DATABASE htqweb_migtest` → `docker exec -e DB_HOST=db -e DB_NAME=htqweb_migtest <svc> alembic upgrade head`.
- **"Whole app frozen / login hangs ~120s" = PgBouncer pool exhaustion**, not a frontend bug. Check first:
  ```bash
  docker exec htqweb1-db-1 psql -U htqweb -d htqweb -c \
    "SELECT state,count(*) FROM pg_stat_activity WHERE usename='htqweb' GROUP BY 1;"
  ```
  ~20 `idle in transaction` (= `DEFAULT_POOL_SIZE`, shared by all services) means orphaned transactions jammed the pool. PgBouncer now reaps them (`IDLE_TRANSACTION_TIMEOUT`/`SERVER_IDLE_TIMEOUT` in compose); recover manually with `pg_terminate_backend` on old idle-in-transaction pids. After recreating PgBouncer, each service's first request 500s once (stale SQLAlchemy pool, no `pool_pre_ping`) then self-heals.

## Host / Windows environment notes

- Shell is PowerShell 5.1; a Bash tool (Git Bash) is also available. **PowerShell mangles `$`, inner quotes, and JSON** in `docker exec`/`psql` args — route anything with `$`, quotes, or JSON bodies through the Bash tool.
- From the Windows host, reach the project DB via **`localhost:6432`** (PgBouncer). Host `:5432` is a native Windows PostgreSQL install, not the container.
- `DB_NAME=htqweb`, `DB_USER=htqweb`, dev password `change-me` (root `.env`).

## Observability

Prometheus (`:9090/prometheus`) scrapes all services' `/metrics` (added via `htqweb_metrics`), the DB/redis/mongo exporters, MinIO, Loki, and Grafana — 16 targets. Grafana (`:3001`, or `/grafana/` via the edge) has SSO: platform accounts sign in with their JWT (superuser→Admin, staff→Editor); dashboards live in the **HTQWeb** folder. Config in `infra/logging/`. Seed test traffic with `scripts/generate-monitoring-traffic.sh`.
