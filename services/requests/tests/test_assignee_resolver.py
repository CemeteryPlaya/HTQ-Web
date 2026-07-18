import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.models import Base
from app.models.project import RequestProject
from app.models.project_member import ProjectMemberRole, RequestProjectMember
from app.services.assignee_resolver import resolve_assignees, AssigneeResolutionError


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


async def test_user_kind(session):
    ids = await resolve_assignees(session, {"kind": "user", "id": 42}, initiator_id=1, project_id=None)
    assert ids == [42]


async def test_project_admins_kind(session):
    p = RequestProject(name="P")
    session.add(p)
    await session.flush()
    session.add_all([
        RequestProjectMember(project_id=p.id, user_id=10, role=ProjectMemberRole.ADMIN),
        RequestProjectMember(project_id=p.id, user_id=11, role=ProjectMemberRole.ADMIN),
        RequestProjectMember(project_id=p.id, user_id=12, role=ProjectMemberRole.MEMBER),
    ])
    await session.flush()
    ids = await resolve_assignees(session, {"kind": "project_admins"}, initiator_id=1, project_id=p.id)
    assert sorted(ids) == [10, 11]


async def test_user_kind_without_id_raises(session):
    with pytest.raises(AssigneeResolutionError):
        await resolve_assignees(session, {"kind": "user"}, initiator_id=1, project_id=None)


async def test_users_kind_returns_list(session):
    ids = await resolve_assignees(session, {"kind": "users", "ids": [7, 8, 9]}, initiator_id=1, project_id=None)
    assert ids == [7, 8, 9]


async def test_users_kind_empty_raises(session):
    with pytest.raises(AssigneeResolutionError):
        await resolve_assignees(session, {"kind": "users", "ids": []}, initiator_id=1, project_id=None)


async def test_initiator_kind_returns_initiator(session):
    ids = await resolve_assignees(session, {"kind": "initiator"}, initiator_id=42, project_id=None)
    assert ids == [42]


async def test_project_admins_without_project_raises(session):
    with pytest.raises(AssigneeResolutionError):
        await resolve_assignees(session, {"kind": "project_admins"}, initiator_id=1, project_id=None)


async def test_unsupported_kind_raises(session):
    with pytest.raises(AssigneeResolutionError):
        await resolve_assignees(session, {"kind": "department_head"}, initiator_id=1, project_id=5)


# ─── Phase 4a additions ───────────────────────────────────────────────────


async def test_role_kind_returns_elevated_users(session):
    from app.models.user_replica import RequestUser
    session.add_all([
        RequestUser(id=1, username="elev1", is_elevated=True),
        RequestUser(id=2, username="elev2", is_elevated=True),
        RequestUser(id=3, username="plain", is_elevated=False),
    ])
    await session.flush()
    ids = await resolve_assignees(session, {"kind": "role"}, initiator_id=99, project_id=None)
    assert sorted(ids) == [1, 2]


async def test_field_ref_returns_user_from_form(session):
    ids = await resolve_assignees(
        session, {"kind": "field_ref", "field": "boss"},
        initiator_id=99, project_id=None, form_values={"boss": 77},
    )
    assert ids == [77]


async def test_field_ref_with_list_value(session):
    ids = await resolve_assignees(
        session, {"kind": "field_ref", "field": "approvers"},
        initiator_id=99, project_id=None, form_values={"approvers": [10, 11]},
    )
    assert sorted(ids) == [10, 11]


async def test_field_ref_missing_value_raises(session):
    with pytest.raises(AssigneeResolutionError):
        await resolve_assignees(
            session, {"kind": "field_ref", "field": "boss"},
            initiator_id=99, project_id=None, form_values={},
        )


# ─── Phase 4b: hr-backed initiator_supervisor / department_head ──────────


async def test_initiator_supervisor_calls_hr(session, monkeypatch):
    captured = {}

    async def _stub(user_id):
        captured["user_id"] = user_id
        return 555

    from app.services import assignee_resolver as _mod
    # patch the bound name inside the resolver module
    import app.services.hr_client as _hr
    monkeypatch.setattr(_hr, "fetch_supervisor_user_id", _stub)

    ids = await resolve_assignees(
        session, {"kind": "initiator_supervisor"}, initiator_id=42, project_id=None,
    )
    assert ids == [555]
    assert captured["user_id"] == 42


async def test_department_head_falls_back_to_same_endpoint(session, monkeypatch):
    async def _stub(user_id):
        return 777

    import app.services.hr_client as _hr
    monkeypatch.setattr(_hr, "fetch_supervisor_user_id", _stub)

    ids = await resolve_assignees(
        session, {"kind": "department_head"}, initiator_id=42, project_id=None,
    )
    assert ids == [777]


async def test_no_supervisor_raises(session, monkeypatch):
    async def _stub(user_id):
        return None

    import app.services.hr_client as _hr
    monkeypatch.setattr(_hr, "fetch_supervisor_user_id", _stub)

    with pytest.raises(AssigneeResolutionError):
        await resolve_assignees(
            session, {"kind": "initiator_supervisor"}, initiator_id=42, project_id=None,
        )
