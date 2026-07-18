import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.models import Base
from app.models.form_template import RequestFormTemplate, RequestFormTemplateVersion
from app.models.project import RequestProject
from app.models.project_member import ProjectMemberRole, RequestProjectMember
from app.models.request_instance import RequestInstance, RequestStatus
from app.repositories.instance_repo import InstanceRepository
from app.services import request_runtime as rr

_SCHEMA = {"fields": [
    {"type": "money", "key": "amount", "label": "Amount", "required": True, "contributes_to_total": True},
]}


def _wf_single_any():
    return {"nodes": [
        {"id": "s", "type": "start"},
        {"id": "a", "type": "approval", "assignee": {"kind": "project_admins"}, "mode": "any"},
        {"id": "ok", "type": "end_approved"},
        {"id": "no", "type": "end_rejected"}],
        "edges": [{"from": "s", "to": "a"},
                  {"from": "a", "to": "ok", "on": "approve"},
                  {"from": "a", "to": "no", "on": "reject"}]}


def _wf_two_all():
    return {"nodes": [
        {"id": "s", "type": "start"},
        {"id": "a", "type": "approval", "assignee": {"kind": "project_admins"}, "mode": "all"},
        {"id": "ok", "type": "end_approved"},
        {"id": "no", "type": "end_rejected"}],
        "edges": [{"from": "s", "to": "a"},
                  {"from": "a", "to": "ok", "on": "approve"},
                  {"from": "a", "to": "no", "on": "reject"}]}


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


async def _make(session, workflow, admin_ids=(10,)):
    p = RequestProject(name="P")
    session.add(p)
    await session.flush()
    for uid in admin_ids:
        session.add(RequestProjectMember(project_id=p.id, user_id=uid, role=ProjectMemberRole.ADMIN))
    tpl = RequestFormTemplate(project_id=p.id, name="T", slug="t")
    session.add(tpl)
    await session.flush()
    ver = RequestFormTemplateVersion(template_id=tpl.id, version=1, schema_json=_SCHEMA, workflow_json=workflow)
    session.add(ver)
    await session.flush()
    inst = RequestInstance(
        code=f"REQ-t-2026-{tpl.id:04d}", template_id=tpl.id, template_version_id=ver.id,
        project_id=p.id, initiator_id=1, title="x", form_values_json={"amount": 100},
        status=RequestStatus.DRAFT.value,
    )
    session.add(inst)
    await session.flush()
    return inst


async def test_submit_assigns_first_approval(session):
    inst = await _make(session, _wf_single_any())
    await rr.submit(session, inst, actor_id=1)
    assert inst.status == RequestStatus.PENDING.value
    assert inst.current_node_id == "a"
    assert inst.total_amount == 100
    actions = await InstanceRepository(session).live_actions(inst.id, "a")
    assert {a.approver_id for a in actions} == {10}


async def test_approve_any_finalizes_approved(session):
    inst = await _make(session, _wf_single_any())
    await rr.submit(session, inst, actor_id=1)
    await rr.act(session, inst, approver_id=10, action="approve")
    assert inst.status == RequestStatus.APPROVED.value
    assert inst.current_node_id is None
    assert inst.finalized_at is not None


async def test_reject_finalizes_rejected(session):
    inst = await _make(session, _wf_single_any())
    await rr.submit(session, inst, actor_id=1)
    await rr.act(session, inst, approver_id=10, action="reject", comment="no")
    assert inst.status == RequestStatus.REJECTED.value


async def test_non_approver_cannot_act(session):
    inst = await _make(session, _wf_single_any())
    await rr.submit(session, inst, actor_id=1)
    with pytest.raises(Exception):
        await rr.act(session, inst, approver_id=999, action="approve")


async def test_request_changes_returns_then_resubmit(session):
    inst = await _make(session, _wf_single_any())
    await rr.submit(session, inst, actor_id=1)
    await rr.act(session, inst, approver_id=10, action="request_changes", comment="fix")
    assert inst.status == RequestStatus.RETURNED.value
    assert inst.current_node_id is None
    await rr.submit(session, inst, actor_id=1)
    assert inst.status == RequestStatus.PENDING.value
    assert inst.current_node_id == "a"


async def test_mode_all_needs_both(session):
    inst = await _make(session, _wf_two_all(), admin_ids=(10, 11))
    await rr.submit(session, inst, actor_id=1)
    await rr.act(session, inst, approver_id=10, action="approve")
    assert inst.status == RequestStatus.PENDING.value
    await rr.act(session, inst, approver_id=11, action="approve")
    assert inst.status == RequestStatus.APPROVED.value


async def test_cancel_by_initiator(session):
    inst = await _make(session, _wf_single_any())
    await rr.submit(session, inst, actor_id=1)
    await rr.cancel(session, inst, actor_id=1, is_elevated=False)
    assert inst.status == RequestStatus.CANCELLED.value
