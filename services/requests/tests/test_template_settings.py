import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from app.models import Base
from app.models.form_template import RequestFormTemplate
from app.services.template_settings import settings_for_template


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    async with engine.begin() as c: await c.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)() as s: yield s
    await engine.dispose()


async def test_defaults_when_no_settings(session):
    t = RequestFormTemplate(name="X", slug="x", config_json={})
    session.add(t); await session.flush()
    s = await settings_for_template(session, t.id)
    assert s["allow_revoke_pending"] is True
    assert s["dedup"] == "none"
    assert s["exclude_efficiency"] is False


async def test_overrides_merge(session):
    t = RequestFormTemplate(name="Y", slug="y", config_json={"settings": {"dedup": "once_auto", "revoke_within_days": 7}})
    session.add(t); await session.flush()
    s = await settings_for_template(session, t.id)
    assert s["dedup"] == "once_auto"
    assert s["revoke_within_days"] == 7
    assert s["allow_revoke_pending"] is True  # still defaulted
