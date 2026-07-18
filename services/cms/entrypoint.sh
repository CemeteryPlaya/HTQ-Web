#!/bin/sh
# Default web entrypoint: run Alembic migrations (if any) then launch uvicorn.
# Worker processes use a different command (see docker-compose.yml).

set -e
export PYTHONPATH="${PYTHONPATH:-/app:/app/libs}"

if [ -f alembic.ini ]; then
  # Migrations bypass pgbouncer (asyncpg + transaction-pool kills the first
  # BEGIN). Runtime uvicorn keeps DB_HOST=pgbouncer from the compose env.
  DB_HOST=db DB_PORT=5432 alembic upgrade head
fi

exec uvicorn app.main:app --host 0.0.0.0 --port "${SERVICE_PORT:-8001}"
