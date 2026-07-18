"""Tests for the deferred reminder + escalation logic.

The Dramatiq actor wrappers `schedule_reminder` / `schedule_escalation` simply
``asyncio.run`` the underlying `_run_reminder` / `_run_escalation` coroutines —
we test those directly to keep the suite Redis-free."""

from datetime import datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.models import Base
from app.models.approval_action import ApprovalAction
from app.models.request_instance import RequestInstance, RequestStatus
from app.models.notifications_log import NotificationsLog
from app.workers import notifications as _notif


@pytest.fixture
async def factory(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    fac = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # Wire the actor's _run_* functions to use this in-memory engine.
    from app import db as _db
    monkeypatch.setattr(_db, "async_session_factory", fac)
    yield fac
    await engine.dispose()


async def _seed(session: AsyncSession) -> tuple[RequestInstance, ApprovalAction]:
    inst = RequestInstance(
        code="REQ-t-2026-0001", template_id=1, template_version_id=1, project_id=None,
        initiator_id=1, title="x", form_values_json={}, status=RequestStatus.PENDING.value,
        current_node_id="a",
    )
    session.add(inst)
    await session.flush()
    action = ApprovalAction(request_id=inst.id, node_id="a", approver_id=10)
    session.add(action)
    await session.commit()  # persist for the next session that the actor opens
    return inst, action


async def test_reminder_noop_when_acted(factory):
    async with factory() as s:
        inst, action = await _seed(s)
        action.action = "approve"
        action.acted_at = datetime.now(timezone.utc)
        await s.commit()
        aid = action.id
    await _notif._run_reminder(aid)
    async with factory() as s:
        rows = (await s.execute(select(NotificationsLog).where(NotificationsLog.kind == "reminder"))).scalars().all()
        assert rows == []


async def test_reminder_fires_when_live(factory):
    async with factory() as s:
        inst, action = await _seed(s)
        aid = action.id
    await _notif._run_reminder(aid)
    async with factory() as s:
        rows = (await s.execute(select(NotificationsLog).where(NotificationsLog.kind == "reminder"))).scalars().all()
        assert len(rows) == 1
        assert rows[0].recipient_id == 10
        a = await s.get(ApprovalAction, aid)
        assert a.reminders_sent == 1


async def test_reminder_noop_when_instance_finalized(factory):
    async with factory() as s:
        inst, action = await _seed(s)
        inst.status = RequestStatus.APPROVED.value
        inst.current_node_id = None
        await s.commit()
        aid = action.id
    await _notif._run_reminder(aid)
    async with factory() as s:
        rows = (await s.execute(select(NotificationsLog).where(NotificationsLog.kind == "reminder"))).scalars().all()
        assert rows == []


async def test_escalation_sets_admin_attention_flag(factory):
    async with factory() as s:
        inst, action = await _seed(s)
        aid = action.id
        iid = inst.id
    await _notif._run_escalation(aid)
    async with factory() as s:
        refreshed = await s.get(RequestInstance, iid)
        assert refreshed.requires_admin_attention is True
        rows = (await s.execute(select(NotificationsLog).where(NotificationsLog.kind == "escalation"))).scalars().all()
        assert len(rows) == 1


async def test_escalation_noop_when_acted(factory):
    async with factory() as s:
        inst, action = await _seed(s)
        action.action = "reject"
        action.acted_at = datetime.now(timezone.utc)
        await s.commit()
        aid = action.id
        iid = inst.id
    await _notif._run_escalation(aid)
    async with factory() as s:
        refreshed = await s.get(RequestInstance, iid)
        assert refreshed.requires_admin_attention is False
