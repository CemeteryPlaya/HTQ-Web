"""Tests for the user-deactivation handler — live approval slots auto-skip."""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.models import Base
from app.models.approval_action import ApprovalAction, ApprovalActionType
from app.models.form_template import RequestFormTemplate, RequestFormTemplateVersion
from app.models.project import RequestProject
from app.models.project_member import ProjectMemberRole, RequestProjectMember
from app.models.request_instance import RequestInstance, RequestStatus
from app.services.request_runtime import handle_user_deactivated


_SCHEMA = {"fields": [{"type": "money", "key": "amount", "label": "Amount", "required": True}]}
_WF = {"nodes": [
    {"id": "s", "type": "start"},
    {"id": "a", "type": "approval", "assignee": {"kind": "project_admins"}, "mode": "any"},
    {"id": "ok", "type": "end_approved"},
    {"id": "no", "type": "end_rejected"}],
    "edges": [{"from": "s", "to": "a"}, {"from": "a", "to": "ok", "on": "approve"},
              {"from": "a", "to": "no", "on": "reject"}]}


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    fac = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with fac() as s:
        yield s
    await engine.dispose()


async def _seed(session: AsyncSession, approver_ids: tuple[int, ...]) -> RequestInstance:
    p = RequestProject(name="P")
    session.add(p)
    await session.flush()
    for uid in approver_ids:
        session.add(RequestProjectMember(project_id=p.id, user_id=uid, role=ProjectMemberRole.ADMIN))
    tpl = RequestFormTemplate(project_id=p.id, name="T", slug="t")
    session.add(tpl)
    await session.flush()
    ver = RequestFormTemplateVersion(template_id=tpl.id, version=1, schema_json=_SCHEMA, workflow_json=_WF)
    session.add(ver)
    await session.flush()
    inst = RequestInstance(
        code=f"REQ-t-2026-{tpl.id:04d}", template_id=tpl.id, template_version_id=ver.id,
        project_id=p.id, initiator_id=1, title="x", form_values_json={"amount": 100},
        status=RequestStatus.PENDING.value, current_node_id="a",
    )
    session.add(inst)
    await session.flush()
    for uid in approver_ids:
        session.add(ApprovalAction(request_id=inst.id, node_id="a", approver_id=uid))
    await session.flush()
    return inst


async def test_deactivation_auto_skips_only_target_user(session):
    inst = await _seed(session, approver_ids=(10, 11))
    await handle_user_deactivated(session, 10)
    rows = (await session.execute(
        select(ApprovalAction).where(ApprovalAction.request_id == inst.id)
    )).scalars().all()
    by_user = {a.approver_id: a for a in rows}
    assert by_user[10].action == ApprovalActionType.AUTO_SKIP.value
    assert by_user[10].acted_at is not None
    # user 11 still live
    assert by_user[11].action is None
    assert by_user[11].acted_at is None
    # request is flagged for admin attention
    assert inst.requires_admin_attention is True
    # status still pending (user 11 can still act)
    assert inst.status == RequestStatus.PENDING.value


async def test_deactivation_noop_when_no_live_actions(session):
    inst = await _seed(session, approver_ids=(10,))
    # mark user 10's action as acted_at to simulate they already responded
    a = (await session.execute(select(ApprovalAction).where(ApprovalAction.approver_id == 10))).scalar_one()
    from datetime import datetime, timezone
    a.action = "approve"
    a.acted_at = datetime.now(timezone.utc)
    await session.flush()
    touched = await handle_user_deactivated(session, 10)
    assert touched == 0


async def test_deactivation_idempotent(session):
    inst = await _seed(session, approver_ids=(10, 11))
    await handle_user_deactivated(session, 10)
    again = await handle_user_deactivated(session, 10)
    assert again == 0  # already skipped
