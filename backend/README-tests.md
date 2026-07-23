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

So `docker-compose.test.yml` (repo root) — **самодостаточный** стек: поднимает
ТОЛЬКО одноразовый Postgres на `55432` (`.env`-var `DB_HOST_PORT`), в отдельном
проекте `htqweb-test` и отдельном volume. Боевую БД (в Docker на VPS `45.10.110.212`,
`docker-compose.yml`) НЕ трогает.

## What to start

```bash
docker compose -f docker-compose.test.yml up -d          # тест-Postgres на :55432
# ...прогнать pytest...
docker compose -f docker-compose.test.yml down -v        # снести с данными
```

⚠️ Поднимать/пересоздавать db ТОЛЬКО через `compose up -d` — **НЕ `docker restart`**:
плоский restart НЕ применяет публикацию порта `:55432` → pytest виснет на
`psycopg ConnectionTimeout` (localhost→`::1`+`127.0.0.1`, timeout 130s каждый).
Проверка: `docker port htqweb-test-db-1` должен показать `0.0.0.0:55432`.
Креды тестовой БД (`htqweb/change-me`) независимы от боевых (`settings/test.py`
читает `TEST_DB_*`, не `DB_*`), поэтому VPS-креды из `.env` сюда не текут.

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
