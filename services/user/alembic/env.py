"""Alembic environment configuration."""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool, text
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.core.settings import settings
from app.models.user import Base as UserBase

config = context.config

# Override sqlalchemy.url from environment
config.set_main_option("sqlalchemy.url", settings.db_dsn)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = UserBase.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table_schema=settings.db_schema,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        version_table_schema=settings.db_schema,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations in 'online' mode with async engine.

    ``statement_cache_size=0`` disables asyncpg's server-side prepared
    statement cache. Without it, pgbouncer in transaction-pooling mode
    closes the connection mid-handshake on the very first ``BEGIN`` —
    each ``alembic upgrade head`` invocation through pgbouncer aborts
    before opening a connection. The setting is a no-op when we connect
    directly to postgres (e.g. ``DB_HOST=db DB_PORT=5432``), so we keep
    it on unconditionally.
    """
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        connect_args={"statement_cache_size": 0, "prepared_statement_cache_size": 0},
    )

    async with connectable.connect() as connection:
        await connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {settings.db_schema}"))
        await connection.commit()
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
