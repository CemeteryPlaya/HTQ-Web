"""Database connection and session management."""

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
    pool_timeout=30,
    pool_recycle=3600,
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


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency that yields a database session.
    Use in FastAPI route handlers:
        async def my_route(db: AsyncSession = Depends(get_db_session)):
    """
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise

# Alias for backward compatibility if needed
get_db = get_db_session
