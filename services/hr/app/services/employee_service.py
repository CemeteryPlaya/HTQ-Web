"""Employee service — business logic for employee management."""

import structlog
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.employee import Employee
from app.repositories.employee_repo import EmployeeRepository
from app.repositories.base_repo import BaseRepository
from app.models.department import Department
from app.models.position import Position
from app.schemas.employee import EmployeeCreate, EmployeeUpdate, EmployeeTransfer
from app.services.audit_service import AuditService
from app.workers.actors import employee_deleted, employee_upserted

logger = structlog.get_logger()


def _employee_event_payload(employee: Employee) -> dict:
    return {
        "id": employee.id,
        "user_id": employee.user_id,
        "email": employee.email,
        "first_name": employee.first_name,
        "last_name": employee.last_name,
        "department_id": employee.department_id,
        "position_id": employee.position_id,
        "status": employee.status,
        "is_deleted": employee.is_deleted,
    }


class EmployeeService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = EmployeeRepository(session)
        self.dept_repo = BaseRepository(Department, session)
        self.pos_repo = BaseRepository(Position, session)
        self.audit = AuditService(session)

    async def _assert_department_exists(self, department_id: int) -> None:
        if not await self.dept_repo.get(department_id):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Department not found")

    async def _assert_position_exists(self, position_id: int) -> None:
        if not await self.pos_repo.get(position_id):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Position not found")

    async def list_employees(
        self,
        *,
        department_id: int | None = None,
        status: str | None = None,
        search: str | None = None,
        page: int = 1,
        limit: int = 20,
    ) -> tuple[list[Employee], int]:
        offset = (page - 1) * limit
        return await self.repo.list_active(
            department_id=department_id,
            status=status,
            search=search,
            offset=offset,
            limit=limit,
        )

    async def get_employee(self, id: int) -> Employee:
        employee = await self.repo.get_with_relations(id)
        if not employee:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")
        return employee

    async def create_employee(self, data: EmployeeCreate, changed_by_id: int) -> Employee:
        await self._assert_department_exists(data.department_id)
        await self._assert_position_exists(data.position_id)

        existing = await self.repo.get_by_email(data.email)
        if existing:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already in use")

        employee = await self.repo.create(data.model_dump())
        await self.audit.log(
            entity_type="employee",
            entity_id=employee.id,
            action="create",
            new_values=data.model_dump(mode="json"),
            changed_by=changed_by_id,
        )
        employee_upserted.send(_employee_event_payload(employee))
        logger.info("employee_created", employee_id=employee.id, changed_by=changed_by_id)
        return await self.repo.get_with_relations(employee.id)

    async def update_employee(self, id: int, data: EmployeeUpdate, changed_by_id: int) -> Employee:
        employee = await self.get_employee(id)
        patch = data.model_dump(exclude_none=True)

        if "department_id" in patch:
            await self._assert_department_exists(patch["department_id"])
        if "position_id" in patch:
            await self._assert_position_exists(patch["position_id"])
        if "email" in patch and patch["email"] != employee.email:
            if await self.repo.get_by_email(patch["email"]):
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already in use")

        old_values = {k: getattr(employee, k) for k in patch}
        updated = await self.repo.update(employee, patch)
        await self.audit.log(
            entity_type="employee",
            entity_id=id,
            action="update",
            old_values={k: str(v) for k, v in old_values.items()},
            new_values={k: str(v) for k, v in patch.items()},
            changed_by=changed_by_id,
        )
        employee_upserted.send(_employee_event_payload(updated))
        logger.info("employee_updated", employee_id=id, changed_by=changed_by_id)
        return await self.repo.get_with_relations(updated.id)

    async def delete_employee(self, id: int, changed_by_id: int) -> None:
        employee = await self.get_employee(id)
        await self.repo.soft_delete(employee)
        await self.audit.log(
            entity_type="employee",
            entity_id=id,
            action="delete",
            changed_by=changed_by_id,
        )
        employee_deleted.send(_employee_event_payload(employee))
        logger.info("employee_deleted", employee_id=id, changed_by=changed_by_id)

    async def transfer_employee(self, id: int, data: EmployeeTransfer, changed_by_id: int) -> Employee:
        employee = await self.get_employee(id)
        await self._assert_department_exists(data.department_id)
        if data.position_id:
            await self._assert_position_exists(data.position_id)

        patch: dict = {"department_id": data.department_id}
        if data.position_id:
            patch["position_id"] = data.position_id

        old_dept = employee.department_id
        updated = await self.repo.update(employee, patch)
        await self.audit.log(
            entity_type="employee",
            entity_id=id,
            action="update",
            old_values={"department_id": str(old_dept)},
            new_values={"department_id": str(data.department_id)},
            changed_by=changed_by_id,
        )
        employee_upserted.send(_employee_event_payload(updated))
        logger.info("employee_transferred", employee_id=id, new_dept=data.department_id)
        return await self.repo.get_with_relations(updated.id)
