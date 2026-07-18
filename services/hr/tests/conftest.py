"""Shared test fixtures for HR service tests."""

import asyncio
from collections.abc import AsyncGenerator
from datetime import datetime, timedelta, timezone

import jwt as pyjwt
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

# Import all models to populate Base.metadata
from app.models import base as _base  # noqa: F401
import app.models  # noqa: F401  - registers all models with Base

Base = _base.Base


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
def pg_url() -> str:
    """Return a Postgres DSN for tests.

    Resolution order: ``TEST_DATABASE_URL`` env var → testcontainers (host run) →
    ``localhost:5432`` fallback.
    """
    import os

    env_url = os.environ.get("TEST_DATABASE_URL")
    if env_url:
        yield env_url
        return

    try:
        from testcontainers.postgres import PostgresContainer

        pg = PostgresContainer("postgres:16-alpine", driver="asyncpg")
        pg.start()
        url = pg.get_connection_url().replace("psycopg2", "asyncpg").replace(
            "postgresql://", "postgresql+asyncpg://"
        )
        if "postgresql+asyncpg" not in url:
            url = url.replace("postgresql://", "postgresql+asyncpg://")
        yield url
        pg.stop()
    except Exception:
        yield "postgresql+asyncpg://htqweb:htqweb@localhost:5432/htqweb_test"


@pytest_asyncio.fixture(scope="session")
async def async_engine(pg_url: str):
    engine = create_async_engine(
        pg_url,
        echo=False,
        poolclass=NullPool,
        connect_args={"server_settings": {"search_path": "public"}},
    )
    async with engine.begin() as conn:
        # Drop+recreate hr-owned tables in public schema
        for t in reversed(Base.metadata.sorted_tables):
            await conn.execute(text(f'DROP TABLE IF EXISTS public."{t.name}" CASCADE'))
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        for t in reversed(Base.metadata.sorted_tables):
            await conn.execute(text(f'DROP TABLE IF EXISTS public."{t.name}" CASCADE'))
    await engine.dispose()


@pytest_asyncio.fixture(autouse=True)
async def _truncate_between_tests(async_engine):
    yield
    async with async_engine.begin() as conn:
        existing = await conn.execute(
            text(
                "SELECT tablename FROM pg_tables WHERE schemaname='public' "
                "AND tablename = ANY(:names)"
            ),
            {"names": [t.name for t in Base.metadata.sorted_tables]},
        )
        names = [f'public."{r[0]}"' for r in existing]
        if names:
            await conn.execute(text("TRUNCATE TABLE " + ", ".join(names) + " RESTART IDENTITY CASCADE"))


@pytest_asyncio.fixture
async def session(async_engine) -> AsyncGenerator[AsyncSession, None]:
    factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as sess:
        yield sess
        await sess.rollback()


@pytest_asyncio.fixture
async def client(async_engine) -> AsyncGenerator[AsyncClient, None]:
    from app.db import get_db_session
    from app.main import app

    factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)

    async def _override_db():
        async with factory() as sess:
            try:
                yield sess
                await sess.commit()
            except Exception:
                await sess.rollback()
                raise

    app.dependency_overrides[get_db_session] = _override_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


# ── Auth helpers ──────────────────────────────────────────────────────────

def make_admin_token(user_id: int = 1, secret: str = "change-me") -> str:
    payload = {
        "sub": str(user_id),
        "user_id": user_id,
        "username": "admin",
        "email": "admin@test.local",
        "is_staff": True,
        "is_superuser": True,
        "is_admin": True,
        "iss": "htqweb-auth",
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
    }
    return pyjwt.encode(payload, secret, algorithm="HS256")


def admin_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {make_admin_token()}"}
