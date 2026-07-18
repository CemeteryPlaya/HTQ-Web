"""Alembic environment configuration for Task Service."""

import asyncio
import logging
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.core.settings import settings
# Import all models so Alembic detects them via Base.metadata
from app.models import Base  # noqa: F401

# Per-service bookkeeping table — keeps task migrations isolated from
# other services that share the same Postgres database.
VERSION_TABLE = "alembic_version_task"

config = context.config

# Override sqlalchemy.url from environment settings
config.set_main_option("sqlalchemy.url", settings.db_dsn)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

logging.getLogger("alembic.runtime.migration").info(
    "task-service alembic bookkeeping: version_table=%s", VERSION_TABLE
)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (generates SQL script)."""
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
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        version_table=VERSION_TABLE,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations in 'online' mode with async engine.

    ``statement_cache_size=0`` disables asyncpg's server-side prepared
    statement cache so alembic survives a pgbouncer transaction-pool —
    otherwise the very first BEGIN closes the connection.
    """
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
