"""EmployeeCardService — build the full employee card payload.

The card aggregates everything a viewer should see on the
``/hr/employees/:id`` page: basic identity, contacts, position, department,
manager, direct reports and active PMO memberships.

Two presentation modes:
- ``mode='full'``  — authenticated HR view. Includes every field returned.
- ``mode='public'`` — share-link view. Strips PII (email/phone), drops
  subordinates' contacts, hides anything financial.

The shape is intentionally JSON-friendly and language-agnostic — the
frontend ``HREmployeeCard`` / ``PublicEmployeeView`` pages render it as-is.
"""

from __future__ import annotations

from typing import Literal

import structlog
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.department import Department
from app.models.employee import Employee
from app.models.position import Position
from app.services.pmo_service import PMOService

logger = structlog.get_logger()

CardMode = Literal["full", "public"]


def _full_name(emp: Employee) -> str:
    parts = [emp.last_name or "", emp.first_name or "", emp.middle_name or ""]
    return " ".join(p for p in parts if p).strip()


def _employee_brief(emp: Employee, *, with_contacts: bool) -> dict:
    out: dict = {
        "id": emp.id,
        "full_name": _full_name(emp),
        "first_name": emp.first_name,
        "last_name": emp.last_name,
        "middle_name": emp.middle_name,
        "avatar_url": emp.avatar_url,
        "position_title": emp.position.title if emp.position else None,
        "department_name": emp.department.name if emp.department else None,
        "status": emp.status,
    }
    if with_contacts:
        out["email"] = emp.email
        out["phone"] = emp.phone
    return out


class EmployeeCardService:
    """Aggregate the employee card payload from across HR tables."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def build_card(self, employee_id: int, *, mode: CardMode = "full", access=None) -> dict:
        emp = await self._load_employee(employee_id)
        if emp is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Employee not found",
            )

        manager = await self._resolve_manager(emp)
        subordinates = await self._resolve_subordinates(emp)
        pmos = await PMOService(self.session).get_employee_pmos(emp.id)
        with_contacts = mode == "full"

        card: dict = {
            "id": emp.id,
            "user_id": emp.user_id,
            "first_name": emp.first_name,
            "last_name": emp.last_name,
            "middle_name": emp.middle_name,
            "full_name": _full_name(emp),
            "avatar_url": emp.avatar_url,
            "bio": emp.bio,
            "status": emp.status,
            "hire_date": emp.hire_date.isoformat() if emp.hire_date else None,
            "termination_date": (
                emp.termination_date.isoformat() if emp.termination_date else None
            ),
            "department": (
                {
                    "id": emp.department.id,
                    "name": emp.department.name,
                    "path": emp.department.path,
                }
                if emp.department
                else None
            ),
            "position": (
                {
                    "id": emp.position.id,
                    "title": emp.position.title,
                    "grade": emp.position.grade,
                    "level": emp.position.level,
                }
                if emp.position
                else None
            ),
            "manager": (
                _employee_brief(manager, with_contacts=with_contacts)
                if manager
                else None
            ),
            "subordinates": [
                _employee_brief(sub, with_contacts=with_contacts) for sub in subordinates
            ],
            "pmos": pmos,
        }

        if mode == "full":
            card["email"] = emp.email
            card["phone"] = emp.phone
        else:
            # Belt-and-braces: never let PII leak to a public-link consumer
            # even if the caller forgets to strip it on the route layer.
            card["email"] = None
            card["phone"] = None

        if mode == "full" and access is not None:
            from app.services.employee_card_t2_service import EmployeeCardT2Service
            card["t2"] = await EmployeeCardT2Service(self.session).read_sections(emp.id, access)
        else:
            card["t2"] = {}

        return card

    async def _load_employee(self, employee_id: int) -> Employee | None:
        stmt = (
            select(Employee)
            .where(Employee.id == employee_id, Employee.is_deleted == False)  # noqa: E712
            .options(
                selectinload(Employee.department),
                selectinload(Employee.position),
            )
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def _resolve_manager(self, emp: Employee) -> Employee | None:
        """Pick the head of the employee's department as their manager.

        The HR schema has a richer reporting-relation matrix
        (``hr_reporting_relations``) but for the card we want a single
        canonical name — the department head is what the org-chart UI uses
        as well. If the employee *is* the head, the next non-self department
        in the ltree path takes over.
        """
        if not emp.department or not emp.department.manager_id:
            return await self._climb_to_parent_manager(emp)

        if emp.department.manager_id == emp.id:
            return await self._climb_to_parent_manager(emp)

        stmt = (
            select(Employee)
            .where(Employee.id == emp.department.manager_id)
            .options(
                selectinload(Employee.department),
                selectinload(Employee.position),
            )
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def _climb_to_parent_manager(self, emp: Employee) -> Employee | None:
        """Walk the ltree path upwards until we find a department with a head."""
        if not emp.department:
            return None
        path_parts = emp.department.path.split(".")
        # Drop the trailing segment to start one level up.
        while len(path_parts) > 1:
            path_parts = path_parts[:-1]
            parent_path = ".".join(path_parts)
            stmt = select(Department).where(Department.path == parent_path)
            parent = (await self.session.execute(stmt)).scalar_one_or_none()
            if parent and parent.manager_id and parent.manager_id != emp.id:
                m_stmt = (
                    select(Employee)
                    .where(Employee.id == parent.manager_id)
                    .options(
                        selectinload(Employee.department),
                        selectinload(Employee.position),
                    )
                )
                return (await self.session.execute(m_stmt)).scalar_one_or_none()
        return None

    async def _resolve_subordinates(self, emp: Employee) -> list[Employee]:
        """All active employees whose department is headed by this employee.

        Direct line only — we do not walk the ltree, so a CEO's card does not
        list the entire company. To expose nested reports the frontend can
        follow each subordinate's own card.
        """
        stmt = (
            select(Department.id)
            .where(Department.manager_id == emp.id, Department.is_active == True)  # noqa: E712
        )
        dept_ids = list((await self.session.execute(stmt)).scalars().all())
        if not dept_ids:
            return []

        stmt = (
            select(Employee)
            .where(
                Employee.department_id.in_(dept_ids),
                Employee.is_deleted == False,  # noqa: E712
                Employee.id != emp.id,
                Employee.status == "active",
            )
            .options(
                selectinload(Employee.department),
                selectinload(Employee.position),
            )
            .order_by(Employee.last_name.asc())
        )
        return list((await self.session.execute(stmt)).scalars().all())
