from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.models import Base
from app.models.form_template import RequestFormTemplate
from app.models.request_instance import RequestInstance
from app.models.stats_daily import RequestStatsDaily
from app.services.stats_rollup import upsert_finalization


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    async with engine.begin() as c: await c.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)() as s: yield s
    await engine.dispose()


async def test_exclude_efficiency_on_skips_timing(session):
    t = RequestFormTemplate(name="Excl", slug="excl", config_json={"settings": {"exclude_efficiency": True}})
    session.add(t); await session.flush()

    finalized = datetime(2026, 7, 10, 12, 0, 0, tzinfo=timezone.utc)
    submitted = finalized - timedelta(hours=1)
    inst = RequestInstance(
        code="EXCL-1", template_id=t.id, template_version_id=1, initiator_id=1,
        status="approved", submitted_at=submitted, finalized_at=finalized, total_amount=None,
    )
    session.add(inst); await session.flush()

    await upsert_finalization(session, inst)

    row = await session.get(RequestStatsDaily, (finalized.date(), 0, t.id))
    assert row is not None
    assert row.approved == 1
    assert row.time_to_decision_seconds_sum == 0


async def test_exclude_efficiency_off_accumulates_timing(session):
    t = RequestFormTemplate(name="Incl", slug="incl", config_json={})
    session.add(t); await session.flush()

    finalized = datetime(2026, 7, 11, 12, 0, 0, tzinfo=timezone.utc)
    submitted = finalized - timedelta(hours=1)
    inst = RequestInstance(
        code="INCL-1", template_id=t.id, template_version_id=1, initiator_id=1,
        status="approved", submitted_at=submitted, finalized_at=finalized, total_amount=None,
    )
    session.add(inst); await session.flush()

    await upsert_finalization(session, inst)

    row = await session.get(RequestStatsDaily, (finalized.date(), 0, t.id))
    assert row is not None
    assert row.approved == 1
    assert row.time_to_decision_seconds_sum > 0
    assert row.time_to_decision_seconds_sum == 3600
