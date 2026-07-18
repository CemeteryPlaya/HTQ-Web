"""Alembic environment configuration for Task Service."""

import asyncio
import logging
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool, text
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.core.settings import settings
# Import all models so Alembic detects them via Base.metadata
from app.models import Base  # noqa: F401

# Per-service bookkeeping table — keeps task migrations isolated from
# other services that share the same Postgres database.
VERSION_TABLE = "alembic_version_media"

config = context.config

# Override sqlalchemy.url from environment settings
config.set_main_option("sqlalchemy.url", settings.db_dsn)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

logging.getLogger("alembic.runtime.migration").info(
    "media-service alembic bookkeeping: version_table=%s", VERSION_TABLE
)

target_metadata = Base.metadata


# Keep autogenerate scoped to this service's own tables — other services share
# the same database and their tables would otherwise show up as "to be dropped".
# Metadata may store schema-qualified names (e.g. "cms.news") when models set
# `__table_args__ = {"schema": "cms"}`; handle both forms.
_OWN_TABLES = frozenset(target_metadata.tables.keys())
_OWN_SCHEMAS = frozenset(
    t.schema for t in target_metadata.tables.values() if t.schema
)


def include_object(obj, name, type_, reflected, compare_to) -> bool:
    if type_ == "table":
        schema = getattr(obj, "schema", None)
        qualified = f"{schema}.{name}" if schema else name
        if qualified in _OWN_TABLES or name in _OWN_TABLES:
            return True
        # Tables reflected from the DB outside of our schemas are other
        # services' territory — leave them alone.
        if reflected and schema not in _OWN_SCHEMAS and schema is not None:
            return False
        if reflected and not _OWN_SCHEMAS:
            # No per-service schema declared on models — conservatively include
            # only tables whose bare name matches a model.
            return False
        return False
    if type_ == "index" and reflected and compare_to is None:
        return False
    return True


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (generates SQL script)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table=VERSION_TABLE,
        include_object=include_object,
        include_schemas=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        version_table=VERSION_TABLE,
        version_table_schema=settings.db_schema,
        include_object=include_object,
        include_schemas=True,
    )

    with context.begin_transaction():
        # Ensure the schema exists before any CREATE TABLE runs. All migrations
        # use explicit `schema=` in op.create_table so we don't need to touch
        # search_path (which would be a no-op under pgbouncer transaction mode
        # anyway: IGNORE_STARTUP_PARAMETERS eats SET search_path).
        connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {settings.db_schema}"))
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
