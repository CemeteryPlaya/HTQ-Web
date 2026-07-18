import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.models import Base
from app.models.notifications_log import NotificationsLog
from app.models.request_instance import RequestInstance, RequestStatus
from app.services import dispatch as dispatch_mod


@pytest.fixture
async def session():
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


@pytest.fixture
def sent(monkeypatch):
    """Replace the bot actor with a recorder local to this test."""
    calls: list = []

    class _Stub:
        @staticmethod
        def send_with_options(args, **kw):
            calls.append(args)

    monkeypatch.setattr(dispatch_mod, "send_bot_message", _Stub)
    return calls


async def _make(session):
    inst = RequestInstance(
        code="REQ-t-2026-0001", template_id=1, template_version_id=1, project_id=None,
        initiator_id=1, title="x", form_values_json={}, status=RequestStatus.PENDING.value,
        current_node_id="a",
    )
    session.add(inst)
    await session.flush()
    return inst


async def test_dispatch_creates_dedup_rows_and_enqueues(session, sent):
    inst = await _make(session)
    await dispatch_mod.dispatch_event(session, inst, "request_assigned", [10, 11])
    assert len(sent) == 2
    bots = {a[0] for a in sent}
    user_ids = {a[1] for a in sent}
    assert bots == {"bot-requests"}
    assert user_ids == {10, 11}
    rows = (await session.execute(select(NotificationsLog))).scalars().all()
    assert len(rows) == 2
    assert {r.recipient_id for r in rows} == {10, 11}
    assert all(r.kind == "request_assigned" for r in rows)


async def test_dispatch_is_idempotent(session, sent):
    inst = await _make(session)
    await dispatch_mod.dispatch_event(session, inst, "request_assigned", [10])
    await dispatch_mod.dispatch_event(session, inst, "request_assigned", [10])
    assert len(sent) == 1
    rows = (await session.execute(select(NotificationsLog))).scalars().all()
    assert len(rows) == 1


async def test_dispatch_distinguishes_kinds(session, sent):
    inst = await _make(session)
    await dispatch_mod.dispatch_event(session, inst, "request_assigned", [10])
    await dispatch_mod.dispatch_event(session, inst, "approved_partial", [10], approver_id=20)
    assert len(sent) == 2
