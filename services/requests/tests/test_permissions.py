import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from htqweb_auth import TokenPayload
from app.models import Base
from app.models.project import RequestProject
from app.models.project_member import ProjectMemberRole, RequestProjectMember
from app.repositories.project_repo import ProjectRepository
from app.auth.permissions import ensure_can_manage_project


def _tok(user_id: int, elevated: bool = False) -> TokenPayload:
    return TokenPayload(user_id=user_id, token_type="access", exp=9999999999, is_staff=elevated)


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


async def test_elevated_user_can_manage_any_project(session):
    p = RequestProject(name="P1")
    session.add(p)
    await session.flush()
    repo = ProjectRepository(session)
    await ensure_can_manage_project(repo, p.id, _tok(1, elevated=True))  # must not raise


async def test_project_admin_can_manage_own_project(session):
    p = RequestProject(name="P2")
    session.add(p)
    await session.flush()
    session.add(RequestProjectMember(project_id=p.id, user_id=5, role=ProjectMemberRole.ADMIN))
    await session.flush()
    repo = ProjectRepository(session)
    await ensure_can_manage_project(repo, p.id, _tok(5))  # must not raise


async def test_plain_member_cannot_manage(session):
    p = RequestProject(name="P3")
    session.add(p)
    await session.flush()
    session.add(RequestProjectMember(project_id=p.id, user_id=6, role=ProjectMemberRole.MEMBER))
    await session.flush()
    repo = ProjectRepository(session)
    with pytest.raises(HTTPException) as exc:
        await ensure_can_manage_project(repo, p.id, _tok(6))
    assert exc.value.status_code == 403


async def test_outsider_cannot_manage(session):
    p = RequestProject(name="P4")
    session.add(p)
    await session.flush()
    repo = ProjectRepository(session)
    with pytest.raises(HTTPException) as exc:
        await ensure_can_manage_project(repo, p.id, _tok(99))
    assert exc.value.status_code == 403
