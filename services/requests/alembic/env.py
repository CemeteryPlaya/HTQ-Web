"""Alembic environment configuration for Requests Service."""

import asyncio
import logging
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.core.settings import settings
from app.models import Base  # noqa: F401  — registers all models on Base.metadata

# Per-service bookkeeping table — keeps requests migrations isolated from
# other services sharing the same Postgres database.
VERSION_TABLE = "alembic_version_requests"

config = context.config
config.set_main_option("sqlalchemy.url", settings.db_dsn)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

logging.getLogger("alembic.runtime.migration").info(
    "requests-service alembic bookkeeping: version_table=%s", VERSION_TABLE
)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table=VERSION_TABLE,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    # Tables live in the `public` schema (the shared pgbouncer drops the
    # search_path startup param, so a dedicated per-service schema isn't
    # reachable at runtime). Table names are prefixed `request_*` for
    # isolation, matching the task-service convention. Do NOT execute any
    # statement before context.configure: alembic must own the transaction
    # so its transactional DDL commits.
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        version_table=VERSION_TABLE,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        connect_args={"statement_cache_size": 0, "prepared_statement_cache_size": 0},
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
