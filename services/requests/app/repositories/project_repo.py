"""Project + membership data access."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import RequestProject
from app.models.project_member import ProjectMemberRole, RequestProjectMember
from app.repositories.base_repo import BaseRepository


class ProjectRepository(BaseRepository[RequestProject]):
    def __init__(self, session: AsyncSession):
        super().__init__(RequestProject, session)

    async def list_ordered(self, offset: int = 0, limit: int = 200) -> list[RequestProject]:
        stmt = select(RequestProject).order_by(RequestProject.created_at.desc()).offset(offset).limit(limit)
        return list((await self.session.execute(stmt)).scalars().all())

    async def get_member(self, project_id: int, user_id: int) -> RequestProjectMember | None:
        return await self.session.get(RequestProjectMember, {"project_id": project_id, "user_id": user_id})

    async def is_project_admin(self, project_id: int, user_id: int) -> bool:
        member = await self.get_member(project_id, user_id)
        return member is not None and member.role == ProjectMemberRole.ADMIN

    async def list_members(self, project_id: int) -> list[RequestProjectMember]:
        stmt = select(RequestProjectMember).where(RequestProjectMember.project_id == project_id)
        return list((await self.session.execute(stmt)).scalars().all())

    async def add_member(
        self, project_id: int, user_id: int, role: ProjectMemberRole, granted_by: int | None
    ) -> RequestProjectMember:
        existing = await self.get_member(project_id, user_id)
        if existing is not None:
            existing.role = role
            await self.session.flush()
            return existing
        member = RequestProjectMember(
            project_id=project_id, user_id=user_id, role=role, granted_by=granted_by
        )
        self.session.add(member)
        await self.session.flush()
        return member

    async def remove_member(self, member: RequestProjectMember) -> None:
        await self.session.delete(member)
        await self.session.flush()
