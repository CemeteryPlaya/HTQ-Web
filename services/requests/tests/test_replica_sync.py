import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.models import Base, RequestUser
from app.workers.replica_sync import (
    _upsert_user_replica,
    _deactivate_user_replica,
)


@pytest.fixture
async def session():
    # In-memory SQLite is enough to exercise the upsert logic in isolation.
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


async def test_upsert_inserts_new_user(session):
    await _upsert_user_replica(session, {
        "id": 7, "username": "ivanov", "email": "i@x.kz",
        "first_name": "Иван", "last_name": "Иванов",
        "is_active": True, "is_elevated": True,
    })
    row = (await session.execute(select(RequestUser).where(RequestUser.id == 7))).scalar_one()
    assert row.username == "ivanov"
    assert row.is_elevated is True
    assert row.full_name == "Иван Иванов"


async def test_upsert_updates_existing_user(session):
    await _upsert_user_replica(session, {"id": 7, "username": "old"})
    await _upsert_user_replica(session, {"id": 7, "username": "new", "first_name": "N"})
    row = (await session.execute(select(RequestUser).where(RequestUser.id == 7))).scalar_one()
    assert row.username == "new"
    assert row.first_name == "N"


async def test_deactivate_sets_flags(session):
    await _upsert_user_replica(session, {"id": 7, "username": "ivanov", "is_active": True})
    await _deactivate_user_replica(session, 7)
    row = (await session.execute(select(RequestUser).where(RequestUser.id == 7))).scalar_one()
    assert row.is_active is False
    assert row.deactivated_at is not None


async def test_deactivate_missing_user_is_noop(session):
    await _deactivate_user_replica(session, 999)  # must not raise
