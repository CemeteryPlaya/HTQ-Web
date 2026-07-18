"""Database setup for Admin."""

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
        # asyncpg + pgbouncer transaction-pool: disable server-side
        # prepared statements (DISCARD ALL between checkouts kills them).
        "statement_cache_size": 0,
        "prepared_statement_cache_size": 0,
    },
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)
