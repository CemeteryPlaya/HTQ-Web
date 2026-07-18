"""Department repository."""

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.department import Department
from app.repositories.base_repo import BaseRepository


class DepartmentRepository(BaseRepository[Department]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(Department, session)

    async def get_with_children(self, id: int) -> Department | None:
        result = await self.session.get(Department, id)
        return result

    async def get_by_path(self, path: str) -> Department | None:
        stmt = select(Department).where(Department.path == path)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_children(self, path: str) -> list[Department]:
        """Return direct children via ltree: path ~ 'parent.*{1}'."""
        # Using LIKE as a portable fallback (proper ltree via raw SQL if needed)
        prefix = path + "."
        stmt = (
            select(Department)
            .where(Department.path.like(f"{prefix}%"))
            .where(Department.is_active == True)  # noqa: E712
            .order_by(Department.name)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_all_active(self) -> list[Department]:
        stmt = select(Department).where(Department.is_active == True).order_by(Department.path)  # noqa: E712
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_all_active_with_positions(self) -> list[Department]:
        """Same as get_all_active, but eager-loads positions for the tree view."""
        stmt = (
            select(Department)
            .where(Department.is_active == True)  # noqa: E712
            .options(selectinload(Department.positions))
            .order_by(Department.path)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_employees(self, department_id: int) -> Department | None:
        stmt = (
            select(Department)
            .where(Department.id == department_id)
            .options(selectinload(Department.employees))
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
