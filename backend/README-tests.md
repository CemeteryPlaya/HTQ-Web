# Backend tests — Postgres

Status: **DONE**. The suite runs against real Postgres (`htqweb1-db-1`), no SQLite
anywhere. Full measurement history for how the port conflict was diagnosed is in
`.superpowers/sdd/task-1.0-report.md` — this file is the "how to run it" recipe.

## Why a dedicated port (55432)

pytest-django needs a **direct** connection to Postgres so it can
`CREATE DATABASE test_htqweb` / drop it after the run. Two existing routes don't work:

- Host `:5432` is occupied by a **native Windows `postgresql-x64-18` service**, which
  wins routing over Docker's port-proxy for the same port — the project's
  `htqweb1-db-1` container is unreachable there from the host.
- Host `:6432` (PgBouncer) does reach the real project DB, but it's
  transaction-pooled, and `CREATE DATABASE`/`DROP DATABASE` cannot pass through a
  pooled connection.

So `docker-compose.test.yml` (repo root, new file) publishes the `db` container on a
free port, `55432` (from the already-present but previously-unwired `.env` var
`DB_HOST_PORT`), **without touching `docker-compose.yml`/`docker-compose.dev.yml`** —
deploy configuration is untouched; this override is test-only infrastructure.

## What to start

```bash
docker compose -f docker-compose.yml -f docker-compose.test.yml up -d db
```

This recreates just the `db` service with the extra port mapping
(`${DB_HOST_PORT:-55432}:5432`, additive to the existing `5432:5432` mapping — it
does not remove or change the production port). Verified after bringing it up that
`localhost:55432` really reaches the **container** (schemas `auth, cms, email, media,
messenger` — Postgres 16.13 Alpine) and not the native Windows Postgres 18.

## Env vars (all have working defaults, override only if needed)

`backend/htqweb/settings/test.py` reads:

| Var | Default |
|---|---|
| `TEST_DB_HOST` | `localhost` |
| `TEST_DB_PORT` | `55432` |
| `TEST_DB_NAME` | `htqweb` |
| `TEST_DB_USER` | `htqweb` |
| `TEST_DB_PASSWORD` | `change-me` |

`CACHES` stays `LocMemCache`; Celery runs eager in tests
(`CELERY_TASK_ALWAYS_EAGER = True`, `CELERY_TASK_EAGER_PROPAGATES = True`, in-memory
broker/backend) — the same synchronous-execution behaviour the old django-q2
`Q_CLUSTER["sync"]` setting used to provide. `JWT_SECRET` stays the fixed test value —
these were already correct/warning-free and are unchanged.

## Running the suite

```bash
cd backend
.venv/Scripts/python -m pytest -q
```

Expect `38 passed` with 0 warnings. pytest-django creates `test_htqweb` on Postgres for
the run and drops it afterward (no `--keepdb` configured in `pytest.ini`).

## Notes for whoever touches this next

- `apps/core/migrations/0001_initial.py` seeds `ServiceStatus` rows for every entry in
  `KNOWN_SERVICES` (`conference` seeded `enabled=False` — SFU stack intentionally not
  wired up yet) via `update_or_create`, both forward and backward — this runs for real
  against Postgres now, unlike SQLite's in-memory throwaway DB.
- Tests that touch seeded rows (`apps/core/tests/test_service_gate.py`) already used
  `ServiceStatus.objects.update_or_create(...)`, not `.create(...)` — this was already
  correct going in, no test needed rewriting for the Postgres move.
- The autouse `clear_service_status_cache` fixture in `apps/core/tests/conftest.py`
  still applies unchanged (it only touches Django's cache, not the DB backend).
