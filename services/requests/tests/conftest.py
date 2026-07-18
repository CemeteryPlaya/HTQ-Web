import os

# htqweb_auth.config is fail-fast: JWT_SECRET must be in the process env
# BEFORE any application import. Set known test values here, first thing.
os.environ.setdefault("JWT_SECRET", "change-me-to-django-secret-key")
os.environ.setdefault("JWT_ALGORITHM", "HS256")
os.environ.setdefault("JWT_ISSUER", "htqweb-auth")

import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.main import app
from app.db import get_db_session
from app.models import Base


class _NullActor:
    """Replacement for the real dramatiq actor in unit tests — no Redis needed."""

    @staticmethod
    def send_with_options(*args, **kw):
        return None

    @staticmethod
    def send(*args, **kw):
        return None


@pytest.fixture(autouse=True)
def _stub_bot_actor(monkeypatch):
    """Stub the bot dispatch actor so tests never reach Redis or messenger."""
    from app.workers import notifications as _notif
    monkeypatch.setattr(_notif, "send_bot_message", _NullActor)
    monkeypatch.setattr(_notif, "schedule_reminder", _NullActor)
    monkeypatch.setattr(_notif, "schedule_escalation", _NullActor)
    from app.services import dispatch as _dispatch
    monkeypatch.setattr(_dispatch, "send_bot_message", _NullActor)

    async def _noop_publish(uid, kind, payload):
        return None
    monkeypatch.setattr(_dispatch, "_publish_sse", _noop_publish)


@pytest.fixture
async def db_engine():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def client(db_engine):
    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)

    async def _override_db():
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db_session] = _override_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()
