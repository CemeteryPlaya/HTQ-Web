"""Database setup for Messenger."""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.settings import settings

engine = create_async_engine(
    settings.db_dsn,
    pool_size=10,
    max_overflow=20,
    connect_args={
        "server_settings": {
            "search_path": settings.db_schema,
        },
        # asyncpg uses server-side prepared statements by default. pgbouncer
        # in transaction-pool mode runs ``DISCARD ALL`` between checkouts —
        # which evicts those prepared plans and makes the next reuse fail
        # with ``connection was closed in the middle of operation``. Disabling
        # the cache forces asyncpg to send queries as plain text (no PREPARE),
        # which is the supported configuration for transaction pooling.
        "statement_cache_size": 0,
        "prepared_statement_cache_size": 0,
    },
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
