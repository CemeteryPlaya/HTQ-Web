"""Staffing-table endpoints. view/manage gated by permission keys."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.hr_access import require_permission
from app.db import get_db_session
from app.schemas.staffing import StaffingLineIn, StaffingLineOut
from app.services.staffing_service import StaffingService, line_out

router = APIRouter(prefix="/staffing", tags=["staffing"])

_VIEW = require_permission("hr.staffing.view")
_MANAGE = require_permission("hr.staffing.manage")


def _svc(db: AsyncSession = Depends(get_db_session)) -> StaffingService:
    return StaffingService(db)


@router.get("/occupancy")
async def occupancy(svc: StaffingService = Depends(_svc), _=Depends(_VIEW)):
    return await svc.occupancy()


@router.get("/summary")
async def summary(svc: StaffingService = Depends(_svc), _=Depends(_VIEW)):
    return await svc.payroll_summary()


@router.get("/", response_model=list[StaffingLineOut])
async def list_lines(department_id: int | None = Query(default=None),
                     svc: StaffingService = Depends(_svc), _=Depends(_VIEW)):
    return [line_out(l) for l in await svc.list_lines(department_id)]


@router.post("/", response_model=StaffingLineOut, status_code=201)
async def create_line(body: StaffingLineIn, svc: StaffingService = Depends(_svc), _=Depends(_MANAGE)):
    return line_out(await svc.create_line(body.model_dump()))


@router.put("/{line_id}", response_model=StaffingLineOut)
async def update_line(line_id: int, body: StaffingLineIn, svc: StaffingService = Depends(_svc), _=Depends(_MANAGE)):
    return line_out(await svc.update_line(line_id, body.model_dump()))


@router.delete("/{line_id}", status_code=204)
async def delete_line(line_id: int, svc: StaffingService = Depends(_svc), _=Depends(_MANAGE)):
    await svc.delete_line(line_id)
