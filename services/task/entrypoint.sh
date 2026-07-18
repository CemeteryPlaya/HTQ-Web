#!/usr/bin/env bash
# Entrypoint for the Task service: run alembic migrations, then uvicorn.
# In dev environments, on migration failure, prints a clean-state recovery hint
# instead of silently restart-looping.

set -euo pipefail

SERVICE_NAME="task-service"
SERVICE_ENV="${SERVICE_ENV:-development}"
APP_PORT="${SERVICE_PORT:-8007}"
UVICORN_RELOAD="${UVICORN_RELOAD:-false}"

echo "[${SERVICE_NAME}] env=${SERVICE_ENV} — running alembic upgrade head"

# Migrations bypass pgbouncer (asyncpg + transaction-pool kills the first
# BEGIN). Runtime uvicorn keeps DB_HOST=pgbouncer from the compose env.
if ! DB_HOST=db DB_PORT=5432 PYTHONPATH=/app:/app/libs alembic upgrade head; then
    echo "[${SERVICE_NAME}] ERROR: alembic upgrade failed."

    if [ "${SERVICE_ENV}" = "development" ]; then
        cat <<'EOF'

────────────────────────────────────────────────────────────────────
  DEV RECOVERY — clean-state reset for task-service
────────────────────────────────────────────────────────────────────
  The task tables likely already exist from a previous run while the
  alembic_version_task bookkeeping table is empty. Reset both, then
  restart the container:

    docker compose exec postgres psql -U "$DB_USER" -d "$DB_NAME" \
      -f /docker-entrypoint-initdb.d/reset_task.sql

  Or run inline:

    DROP TABLE IF EXISTS
        notifications, task_links, task_activities, task_attachments,
        task_comments, task_labels, tasks, project_versions, labels,
        production_days, task_sequence, alembic_version_task
    CASCADE;
    DROP TYPE IF EXISTS versionstatus, linktype, tasktype, priority, status;

  Alternatively, if the existing tables already match revision
  001_initial, stamp instead of dropping:

    docker compose run --rm task-service alembic stamp 001_initial
────────────────────────────────────────────────────────────────────
EOF
    fi
    exit 1
fi

echo "[${SERVICE_NAME}] migrations OK — starting uvicorn on :${APP_PORT}"
UVICORN_ARGS=(app.main:app --host 0.0.0.0 --port "${APP_PORT}")
if [ "${SERVICE_ENV}" = "development" ] && [ "${UVICORN_RELOAD}" = "true" ]; then
    UVICORN_ARGS+=(--reload --reload-dir /app/app)
fi

exec uvicorn "${UVICORN_ARGS[@]}"
