#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="messenger-service"
SERVICE_ENV="${SERVICE_ENV:-development}"
APP_PORT="${SERVICE_PORT:-8008}"

echo "[${SERVICE_NAME}] env=${SERVICE_ENV} — running alembic upgrade head"

# Migrations bypass pgbouncer (asyncpg + transaction-pool kills the first
# BEGIN). Runtime uvicorn keeps DB_HOST=pgbouncer from the compose env.
if ! DB_HOST=db DB_PORT=5432 PYTHONPATH=/app:/app/libs alembic upgrade head; then
    echo "[${SERVICE_NAME}] ERROR: alembic upgrade failed."
    if [ "${SERVICE_ENV}" = "development" ]; then
        echo "Hint: If tables already exist, try 'alembic stamp head' or dropping tables: chat_messages, chat_rooms, chat_participants, etc."
    fi
    exit 1
fi

echo "[${SERVICE_NAME}] migrations OK — starting uvicorn on :${APP_PORT}"
exec uvicorn app.main:app --host 0.0.0.0 --port "${APP_PORT}"
