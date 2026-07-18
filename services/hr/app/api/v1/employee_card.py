"""Т-2 card endpoints (scalars). Per-section RBAC via permission keys."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, TokenPayload
from app.auth.hr_access import require_hr_access, resolve_hr_access
from app.db import get_db_session
from app.schemas.employee_card import EmployeeCardT2Patch
from app.schemas.employee_card_groups import EmployeeGroups
from app.services.employee_card_t2_service import EmployeeCardT2Service
from app.services.employee_groups_service import EmployeeGroupsService
from app.services.employee_service import EmployeeService

router = APIRouter(prefix="/employees", tags=["employee-card"])


async def _visible_employee(employee_id: int, db: AsyncSession, current_user: TokenPayload):
    access = require_hr_access(await resolve_hr_access(db, current_user))
    emp = await EmployeeService(db).get_employee(employee_id)
    if not access.can_see_department(emp.department_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")
    return access


@router.get("/{employee_id}/card/t2")
async def get_card_t2(
    employee_id: int,
    db: AsyncSession = Depends(get_db_session),
    current_user: TokenPayload = Depends(get_current_user),
):
    access = await _visible_employee(employee_id, db, current_user)
    return await EmployeeCardT2Service(db).read_sections(employee_id, access)


@router.patch("/{employee_id}/card/t2")
async def patch_card_t2(
    employee_id: int,
    body: EmployeeCardT2Patch,
    db: AsyncSession = Depends(get_db_session),
    current_user: TokenPayload = Depends(get_current_user),
):
    access = await _visible_employee(employee_id, db, current_user)
    patch = body.model_dump(exclude_unset=True)
    try:
        return await EmployeeCardT2Service(db).upsert(employee_id, patch, access)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))


@router.get("/{employee_id}/card/groups")
async def get_card_groups(
    employee_id: int,
    db: AsyncSession = Depends(get_db_session),
    current_user: TokenPayload = Depends(get_current_user),
):
    access = await _visible_employee(employee_id, db, current_user)
    if not access.has("hr.card.groups.view"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Missing permission: hr.card.groups.view")
    return await EmployeeGroupsService().read(employee_id)


@router.put("/{employee_id}/card/groups")
async def put_card_groups(
    employee_id: int,
    body: EmployeeGroups,
    db: AsyncSession = Depends(get_db_session),
    current_user: TokenPayload = Depends(get_current_user),
):
    access = await _visible_employee(employee_id, db, current_user)
    if not access.has("hr.card.groups.edit"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Missing permission: hr.card.groups.edit")
    return await EmployeeGroupsService().replace(employee_id, body.model_dump(mode="json"))
