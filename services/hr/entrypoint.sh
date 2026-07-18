#!/usr/bin/env bash
# Entrypoint for the HR service: run alembic migrations, then uvicorn.
# In dev environments, on migration failure, prints a clean-state recovery hint
# instead of silently restart-looping.

set -euo pipefail

SERVICE_NAME="hr-service"
SERVICE_ENV="${SERVICE_ENV:-development}"
APP_PORT="${SERVICE_PORT:-8006}"

echo "[${SERVICE_NAME}] env=${SERVICE_ENV} — running alembic upgrade head"

# Bypass pgbouncer for migrations: asyncpg's prepared-statement protocol
# doesn't survive pgbouncer transaction-pool mode (the very first BEGIN
# aborts with "connection was closed in the middle of operation"). The
# direct postgres port (5432 on the ``db`` container) sees only this one
# alembic process and works fine. Runtime uvicorn below inherits the
# env-level DB_HOST / DB_PORT and keeps using the pool normally.
if ! DB_HOST=db DB_PORT=5432 PYTHONPATH=/app:/app/libs alembic upgrade head; then
    echo "[${SERVICE_NAME}] ERROR: alembic upgrade failed."

    if [ "${SERVICE_ENV}" = "development" ]; then
        cat <<'EOF'

────────────────────────────────────────────────────────────────────
  DEV RECOVERY — clean-state reset for hr-service
────────────────────────────────────────────────────────────────────
  The HR tables likely already exist from a previous run while the
  alembic_version_hr bookkeeping table is empty. Reset both, then
  restart the container:

    DROP TABLE IF EXISTS
        hr_shareable_links,
        hr_pmo_members, hr_pmo_positions, hr_pmo_departments, hr_pmos,
        hr_reporting_relations, hr_org_settings,
        hr_level_thresholds,
        hr_audit_log, hr_documents, hr_time_entries, hr_applications,
        hr_vacancies, hr_employees, hr_positions, hr_departments,
        alembic_version_hr
    CASCADE;

  Alternatively, stamp to the latest revision you know is applied:

    docker compose run --rm hr-service alembic stamp 005
────────────────────────────────────────────────────────────────────
EOF
    fi
    exit 1
fi

echo "[${SERVICE_NAME}] migrations OK — starting uvicorn on :${APP_PORT}"
exec uvicorn app.main:app --host 0.0.0.0 --port "${APP_PORT}"
