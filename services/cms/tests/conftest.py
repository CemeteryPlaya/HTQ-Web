"""Shared test fixtures for CMS service tests.

Uses testcontainers to spin up a real PostgreSQL instance,
creates the schema, and provides async session + httpx test client.
"""

import asyncio
from collections.abc import AsyncGenerator

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

from app.models.base import Base

import jwt as pyjwt
from datetime import datetime, timezone, timedelta


@pytest.fixture(scope="session")
def event_loop():
    """Create a session-scoped event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
def pg_url() -> str:
    """Return a Postgres DSN for tests.

    Resolution order:
    1. ``TEST_DATABASE_URL`` env var (preferred for in-container runs against the
       compose ``db`` service — set to ``postgresql+asyncpg://htqweb:htqweb@db:5432/htqweb_test``).
    2. testcontainers (host runs with Docker socket access).
    3. ``postgresql+asyncpg://htqweb:htqweb@localhost:5432/htqweb_test`` fallback.
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

        url = pg.get_connection_url()
        url = url.replace("psycopg2", "asyncpg").replace("postgresql://", "postgresql+asyncpg://")
        if "postgresql+asyncpg" not in url:
            url = url.replace("postgresql://", "postgresql+asyncpg://")

        yield url
        pg.stop()
    except Exception:
        yield "postgresql+asyncpg://htqweb:htqweb@localhost:5432/htqweb_test"


@pytest_asyncio.fixture(scope="session")
async def async_engine(pg_url: str):
    engine = create_async_engine(pg_url, echo=False, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS cms"))
        await conn.execute(text("SET search_path TO cms, public"))
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture(autouse=True)
async def _truncate_between_tests(async_engine):
    """Reset all tables before each test to keep tests isolated."""
    yield
    async with async_engine.begin() as conn:
        await conn.execute(
            text(
                "TRUNCATE TABLE "
                + ", ".join(
                    f'"{t.schema}"."{t.name}"' if t.schema else f'"{t.name}"'
                    for t in Base.metadata.sorted_tables
                )
                + " RESTART IDENTITY CASCADE"
            )
        )


@pytest_asyncio.fixture
async def session(async_engine) -> AsyncGenerator[AsyncSession, None]:
    session_factory = async_sessionmaker(
        async_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as sess:
        yield sess
        await sess.rollback()


@pytest_asyncio.fixture
async def client(async_engine) -> AsyncGenerator[AsyncClient, None]:
    """Provide an httpx AsyncClient wired to the CMS FastAPI app.

    Overrides the DB dependency to use the test engine/session.
    """
    from app.db import get_db_session
    from app.main import app

    session_factory = async_sessionmaker(
        async_engine, class_=AsyncSession, expire_on_commit=False
    )

    async def _override_db():
        async with session_factory() as sess:
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
    """Create a valid admin JWT for testing."""
    payload = {
        "sub": str(user_id),
        "user_id": user_id,
        "is_admin": True,
        "iss": "htqweb-auth",
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
    }
    return pyjwt.encode(payload, secret, algorithm="HS256")


def make_user_token(user_id: int = 2, secret: str = "change-me") -> str:
    """Create a valid non-admin JWT for testing."""
    payload = {
        "sub": str(user_id),
        "user_id": user_id,
        "is_admin": False,
        "iss": "htqweb-auth",
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
    }
    return pyjwt.encode(payload, secret, algorithm="HS256")


def admin_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {make_admin_token()}"}


def user_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {make_user_token()}"}
