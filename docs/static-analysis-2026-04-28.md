# Static Analysis Report — Phase 6.2

**Date:** 2026-04-28
**Branch:** main (commit baseline `20a05dd` + Phase 6.1 work)

## Tools

| Tool   | Version | Scope                                       |
|--------|---------|---------------------------------------------|
| ruff   | 0.15.12 | All `services/**/*.py`                      |
| bandit | 1.8.0   | All `services/**/*.py`, severity ≥ MEDIUM   |
| mypy   | 1.13.0  | Critical paths: auth/, crypto, dlp_scanner  |

## Results

### ruff
**0 errors** after autofix and manual cleanup of 26 remaining issues
(E402 in test conftests, E712 SQLAlchemy filter expressions, F401 unused
imports, F841 unused variables).

### bandit
- **HIGH:   0** ✅
- **MEDIUM: 4** — all `B608` (SQL injection via f-string) in alembic
  migrations `services/{email,messenger}/alembic/versions/003_move_to_own_schema.py`.
  These construct DDL (`ALTER TABLE ... SET SCHEMA ...`) with hard-coded table
  names from a developer-controlled constant; **no user input** flows into
  them. Accepted as false positive.
- **LOW:    146** — mostly `B101` (assert in tests) and `B104` (binding to
  `0.0.0.0` in containerised dev). Not actioned.

### mypy
- **0 errors** on the security-critical paths:
  - `services/user/app/auth/`
  - `services/user/app/services/auth_service.py`
  - `services/email/app/auth/`
  - `services/email/app/services/dlp_scanner.py`
  - `services/email/app/services/crypto.py`

Full per-service mypy run is deferred to a follow-up — many service modules
import third-party packages whose types are missing/incomplete and would
need per-package `# type: ignore[import-untyped]` markers.

## Production bugs surfaced & fixed

While running ruff/tests, the following real bugs were caught and fixed in
the same Phase 6 commits:

1. **task-service:** `current_user.get("id")` called on a Pydantic
   `TokenPayload` (no `.get()` method) in 4 endpoints
   ([tasks.py](../services/task/app/api/v1/tasks.py),
   [links.py](../services/task/app/api/v1/links.py),
   [notifications.py](../services/task/app/api/v1/notifications.py)).
   Replaced with `current_user.user_id`. Smoked via live curl —
   `POST /api/tasks/v1/tasks/` was returning 500 in production.
2. **task-service:** PG_ENUM columns missing `values_callable` →
   SQLAlchemy serialised enum names (uppercase `STORY`) instead of values
   (`story`), Postgres rejected with `InvalidTextRepresentationError`.
   Fixed in `task.py`, `version.py`, `link.py`.
3. **messenger-service:** `POST /api/messenger/v1/rooms/` returned freshly
   created `Room` without eager-loading `participants[].user`, causing
   `MissingGreenlet` on response serialisation. Added `selectinload` round-trip
   after create. Smoked via live curl — was 500 in production.
4. **user-service:** Duplicate index definition for `users.username`
   (`index=True` on column **and** explicit `Index(...)` in
   `__table_args__`) → `Base.metadata.create_all` failed with
   `DuplicateTableError`. Removed redundant `index=True`.

## Known-broken (deferred)

- **task-service** `/api/tasks/v1/calendar/` not yet wired (404 on POST).
  One test marked `@pytest.mark.skip` until Phase 5.5 wire-audit follow-up
  picks it up.

## Additional production fix in same phase

- **task-service** `TaskRepository.get_with_relations()` was using
  `session.get(Task, id, options=...)` which didn't fully eager-load
  selectin children → `MissingGreenlet` on response serialisation.
  Replaced with explicit `select(Task).where(...).options(selectinload(...))`
  pattern. Smoked: `POST /api/tasks/v1/tasks/` now returns 201 with full
  detail payload.
