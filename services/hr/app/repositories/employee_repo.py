"""Employee repository — data access for hr_employees table."""

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.employee import Employee
from app.repositories.base_repo import BaseRepository


class EmployeeRepository(BaseRepository[Employee]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(Employee, session)

    async def get_with_relations(self, id: int) -> Employee | None:
        stmt = (
            select(Employee)
            .where(Employee.id == id, Employee.is_deleted == False)  # noqa: E712
            .options(
                selectinload(Employee.department),
                selectinload(Employee.position),
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> Employee | None:
        stmt = select(Employee).where(Employee.email == email, Employee.is_deleted == False)  # noqa: E712
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_active(
        self,
        *,
        department_id: int | None = None,
        status: str | None = None,
        search: str | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[list[Employee], int]:
        from sqlalchemy import func, or_

        stmt = (
            select(Employee)
            .where(Employee.is_deleted == False)  # noqa: E712
            .options(
                selectinload(Employee.department),
                selectinload(Employee.position),
            )
        )
        if department_id is not None:
            stmt = stmt.where(Employee.department_id == department_id)
        if status is not None:
            stmt = stmt.where(Employee.status == status)
        if search:
            pattern = f"%{search.strip()}%"
            stmt = stmt.where(
                or_(
                    Employee.first_name.ilike(pattern),
                    Employee.last_name.ilike(pattern),
                    Employee.middle_name.ilike(pattern),
                    Employee.email.ilike(pattern),
                    func.concat(Employee.first_name, " ", Employee.last_name).ilike(pattern),
                )
            )

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = stmt.order_by(Employee.last_name.asc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    async def soft_delete(self, employee: Employee) -> Employee:
        employee.is_deleted = True
        employee.status = "terminated"
        self.session.add(employee)
        await self.session.flush()
        await self.session.refresh(employee)
        return employee
