"""Departments API router."""

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db_session
from app.auth.dependencies import get_current_user, TokenPayload
from app.schemas.department import (
    DepartmentCreate,
    DepartmentUpdate,
    DepartmentOut,
    DepartmentTree,
    DepartmentWithPositions,
)
from app.schemas.employee import EmployeeOut
from app.services.department_service import DepartmentService

router = APIRouter(prefix="/departments", tags=["departments"])


def _svc(db: AsyncSession = Depends(get_db_session)) -> DepartmentService:
    return DepartmentService(db)


@router.get("/", response_model=list[DepartmentWithPositions])
async def list_departments(
    svc: DepartmentService = Depends(_svc),
    _: TokenPayload = Depends(get_current_user),
):
    return await svc.list_departments()


@router.get("/tree", response_model=list[DepartmentTree])
async def get_department_tree(
    svc: DepartmentService = Depends(_svc),
    _: TokenPayload = Depends(get_current_user),
):
    return await svc.get_tree()


@router.post("/", response_model=DepartmentOut, status_code=status.HTTP_201_CREATED)
async def create_department(
    body: DepartmentCreate,
    svc: DepartmentService = Depends(_svc),
    _: TokenPayload = Depends(get_current_user),
):
    return await svc.create_department(body)


@router.get("/{id}/", response_model=DepartmentOut)
async def get_department(
    id: int,
    svc: DepartmentService = Depends(_svc),
    _: TokenPayload = Depends(get_current_user),
):
    return await svc.get_department(id)


@router.put("/{id}/", response_model=DepartmentOut)
async def update_department(
    id: int,
    body: DepartmentUpdate,
    svc: DepartmentService = Depends(_svc),
    _: TokenPayload = Depends(get_current_user),
):
    return await svc.update_department(id, body)


@router.delete("/{id}/", status_code=status.HTTP_204_NO_CONTENT)
async def delete_department(
    id: int,
    cascade: bool = Query(
        default=False,
        description=(
            "If true, recursively delete sub-departments, positions, employees, "
            "PMO memberships and reporting relations linked to this department."
        ),
    ),
    svc: DepartmentService = Depends(_svc),
    _: TokenPayload = Depends(get_current_user),
):
    await svc.delete_department(id, cascade=cascade)


@router.get("/{id}/children", response_model=list[DepartmentOut])
async def get_department_children(
    id: int,
    svc: DepartmentService = Depends(_svc),
    _: TokenPayload = Depends(get_current_user),
):
    return await svc.get_children(id)


@router.get("/{id}/employees", response_model=list[EmployeeOut])
async def get_department_employees(
    id: int,
    svc: DepartmentService = Depends(_svc),
    _: TokenPayload = Depends(get_current_user),
):
    return await svc.get_employees(id)
