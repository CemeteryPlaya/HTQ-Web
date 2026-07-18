"""Fine-grained HR access helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.dependencies import TokenPayload
from app.auth.permissions import ALL_KEYS, expand_level
from app.models.employee import Employee

HRLevel = Literal["junior", "middle", "senior", "lead"]


@dataclass(frozen=True)
class HRAccess:
    """Resolved HR scope for the current caller.

    ``permissions`` is the authoritative key-set. ``level`` is retained for
    display only. A ``"*"`` member means "all keys" (admin wildcard).
    """

    level: HRLevel | None
    permissions: frozenset[str] = frozenset()
    employee_id: int | None = None
    department_id: int | None = None

    def has(self, key: str) -> bool:
        return "*" in self.permissions or key in self.permissions

    @property
    def has_access(self) -> bool:
        return self.level is not None or bool(self.permissions)

    @property
    def can_read_all(self) -> bool:
        return self.has("hr.employees.view.all")

    @property
    def can_write_basic(self) -> bool:
        return self.has("hr.employees.edit")

    @property
    def can_create_employee(self) -> bool:
        return self.has("hr.employees.create")

    @property
    def can_transfer_employee(self) -> bool:
        return self.has("hr.employees.transfer")

    @property
    def can_delete_employee(self) -> bool:
        return self.has("hr.employees.delete")

    @property
    def can_manage_user_options(self) -> bool:
        return self.has("hr.users.manage")

    @property
    def can_list_user_options(self) -> bool:
        return self.has("hr.users.list")

    def can_see_department(self, department_id: int | None) -> bool:
        if self.can_read_all:
            return True
        return self.department_id is not None and department_id == self.department_id


def _normalize(value: str | None) -> str:
    return (value or "").strip().lower().replace("_", " ").replace("-", " ")


_VALID_LEVELS: set[HRLevel] = {"junior", "middle", "senior", "lead"}


def _level_from_permissions(position: Employee | None) -> HRLevel | None:
    """If the position has an explicit ``permissions.hr_level``, honor it.

    Permissions live on ``Position.permissions`` and are set by admins via
    the HR positions UI. They override the title-based heuristic so a
    user-created position like "Cпециалист по обучению" can still be
    granted ``middle``/``senior`` HR access without inventing a system
    title for it.
    """
    perms = getattr(position, "permissions", None)
    if not isinstance(perms, dict):
        return None
    hr_level = perms.get("hr_level")
    if hr_level in _VALID_LEVELS:
        return hr_level  # type: ignore[return-value]
    return None


def classify_hr_level(employee: Employee | None) -> HRLevel | None:
    """Infer HR level from the employee's HR department/position.

    Resolution order:
    1. ``position.permissions.hr_level`` — explicit override set by an admin.
    2. Title/department heuristic — legacy fallback for system positions.
    """
    if not employee:
        return None

    # Explicit permissions matrix wins over the heuristic.
    explicit = _level_from_permissions(getattr(employee, "position", None))
    if explicit is not None:
        return explicit

    position = _normalize(getattr(employee.position, "title", None))
    department = _normalize(getattr(employee.department, "name", None))
    haystack = f"{position} {department}"

    is_hr = any(
        marker in haystack
        for marker in (
            "hr",
            "human resources",
            "people",
            "персонал",
            "кадр",
            "эйчар",
        )
    )
    if not is_hr:
        return None

    if any(
        marker in haystack
        for marker in (
            "co hr",
            "cohr",
            "chief hr",
            "chief human resources",
            "chief people",
            "cpo",
            "hr director",
            "director hr",
            "руководитель hr",
            "директор по персоналу",
        )
    ):
        return "lead"

    if any(marker in haystack for marker in ("senior", "lead", "head", "старш", "ведущ")):
        return "senior"

    if any(marker in haystack for marker in ("middle", "middel", "mid ", "manager", "менеджер", "специалист")):
        return "middle"

    if any(marker in haystack for marker in ("junior", "assistant", "trainee", "младш", "ассист", "стаж")):
        return "junior"

    return "junior"


async def resolve_hr_access(db: AsyncSession, current_user: TokenPayload) -> HRAccess:
    """Resolve current user's HR access from JWT and HR employee profile."""
    if current_user.is_admin or current_user.is_staff or current_user.is_superuser:
        return HRAccess(level="lead", permissions=frozenset({"*"}))

    stmt = (
        select(Employee)
        .where(Employee.is_deleted == False)  # noqa: E712
        .options(selectinload(Employee.department), selectinload(Employee.position))
        .limit(1)
    )
    if current_user.email:
        stmt = stmt.where(
            or_(Employee.user_id == current_user.user_id, Employee.email == current_user.email)
        )
    else:
        stmt = stmt.where(Employee.user_id == current_user.user_id)

    employee = (await db.execute(stmt)).scalars().first()
    level = classify_hr_level(employee)
    perms: frozenset[str] = frozenset()
    position = getattr(employee, "position", None) if employee else None
    raw = getattr(position, "permissions", None)
    if isinstance(raw, dict) and isinstance(raw.get("permissions"), list) and raw["permissions"]:
        perms = frozenset(str(p) for p in raw["permissions"]) & ALL_KEYS
    else:
        perms = expand_level(level)
    return HRAccess(
        level=level,
        permissions=perms,
        employee_id=employee.id if employee else None,
        department_id=employee.department_id if employee else None,
    )


def require_hr_access(access: HRAccess) -> HRAccess:
    if not access.has_access:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="HR access required",
        )
    return access


def require_can_write_basic(access: HRAccess) -> HRAccess:
    require_hr_access(access)
    if not access.can_write_basic:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="HR write access required",
        )
    return access


def require_permission(key: str):
    """FastAPI dependency: 403 unless the caller's HRAccess has ``key``."""
    from app.db import get_db_session
    from app.auth.dependencies import get_current_user
    from fastapi import Depends

    async def _dep(
        db: AsyncSession = Depends(get_db_session),
        current_user: TokenPayload = Depends(get_current_user),
    ) -> HRAccess:
        access = await resolve_hr_access(db, current_user)
        if not access.has(key):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing permission: {key}",
            )
        return access

    return _dep
