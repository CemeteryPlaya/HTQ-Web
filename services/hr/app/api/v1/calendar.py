"""Production-calendar endpoints. view/manage gated by permission keys."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, TokenPayload
from app.auth.hr_access import require_hr_access, require_permission, resolve_hr_access
from app.db import get_db_session
from app.schemas.calendar import (
    AssignTemplateIn, CalendarDayIn, CalendarImportItem, WeekTemplateIn, WeekTemplateOut,
    ShiftPatternIn, ShiftPatternOut, AssignShiftIn, EmployeeDayOverrideIn,
)
from app.services.calendar_service import CalendarService
from app.services.employee_service import EmployeeService

router = APIRouter(prefix="/calendar", tags=["calendar"])

_VIEW = require_permission("hr.calendar.view")
_MANAGE = require_permission("hr.calendar.manage")


def _svc(db: AsyncSession = Depends(get_db_session)) -> CalendarService:
    return CalendarService(db)


# ── templates (literal segment before /{day}) ──
@router.get("/templates", response_model=list[WeekTemplateOut])
async def list_templates(svc: CalendarService = Depends(_svc), _=Depends(_VIEW)):
    return await svc.list_templates()


@router.post("/templates", response_model=WeekTemplateOut, status_code=201)
async def create_template(body: WeekTemplateIn, svc: CalendarService = Depends(_svc), _=Depends(_MANAGE)):
    return await svc.create_template(body.name, body.model_dump()["days"])


@router.put("/templates/{template_id}", response_model=WeekTemplateOut)
async def update_template(template_id: int, body: WeekTemplateIn, svc: CalendarService = Depends(_svc), _=Depends(_MANAGE)):
    return await svc.update_template(template_id, body.name, body.model_dump()["days"])


@router.delete("/templates/{template_id}", status_code=204)
async def delete_template(template_id: int, svc: CalendarService = Depends(_svc), _=Depends(_MANAGE)):
    await svc.delete_template(template_id)


@router.post("/templates/{template_id}/default", response_model=WeekTemplateOut)
async def set_default(template_id: int, svc: CalendarService = Depends(_svc), _=Depends(_MANAGE)):
    return await svc.set_default(template_id)


@router.get("/working-days")
async def working_days(start: date = Query(...), end: date = Query(...),
                       svc: CalendarService = Depends(_svc), _=Depends(_VIEW)):
    return await svc.working_days_between(start, end)


@router.post("/import")
async def import_year(items: list[CalendarImportItem], svc: CalendarService = Depends(_svc), _=Depends(_MANAGE)):
    payload = [{"day": it.day, "day_type": it.day_type, "norm_hours": it.norm_hours, "note": it.note} for it in items]
    return {"imported": await svc.import_year(payload)}


@router.get("/")
async def get_year(year: int = Query(...), svc: CalendarService = Depends(_svc), _=Depends(_VIEW)):
    return await svc.list_year(year)


@router.get("/shift-patterns", response_model=list[ShiftPatternOut])
async def list_shift_patterns(svc: CalendarService = Depends(_svc), _=Depends(_VIEW)):
    return await svc.list_shift_patterns()


@router.post("/shift-patterns", response_model=ShiftPatternOut, status_code=201)
async def create_shift_pattern(body: ShiftPatternIn, svc: CalendarService = Depends(_svc), _=Depends(_MANAGE)):
    slots = [s.model_dump() for s in body.slots]
    return await svc.create_shift_pattern(body.name, slots, holidays_off=body.holidays_off)


@router.put("/shift-patterns/{pattern_id}", response_model=ShiftPatternOut)
async def update_shift_pattern(pattern_id: int, body: ShiftPatternIn, svc: CalendarService = Depends(_svc), _=Depends(_MANAGE)):
    slots = [s.model_dump() for s in body.slots]
    return await svc.update_shift_pattern(pattern_id, body.name, slots, body.holidays_off)


@router.delete("/shift-patterns/{pattern_id}", status_code=204)
async def delete_shift_pattern(pattern_id: int, svc: CalendarService = Depends(_svc), _=Depends(_MANAGE)):
    await svc.delete_shift_pattern(pattern_id)


@router.put("/{day}")
async def put_override(day: date, body: CalendarDayIn, svc: CalendarService = Depends(_svc), _=Depends(_MANAGE)):
    o = await svc.upsert_day(day, body.day_type, body.norm_hours, body.note)
    return {"day": o.day.isoformat(), "day_type": o.day_type, "norm_hours": str(o.norm_hours), "note": o.note}


@router.delete("/{day}", status_code=204)
async def delete_override(day: date, svc: CalendarService = Depends(_svc), _=Depends(_MANAGE)):
    await svc.delete_override(day)


employee_calendar_router = APIRouter(prefix="/employees", tags=["calendar"])


async def _visible(employee_id: int, db: AsyncSession, current_user: TokenPayload):
    access = require_hr_access(await resolve_hr_access(db, current_user))
    emp = await EmployeeService(db).get_employee(employee_id)
    if not access.can_see_department(emp.department_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")
    return access


@employee_calendar_router.get("/{employee_id}/calendar")
async def employee_calendar(
    employee_id: int, start: date = Query(...), end: date = Query(...),
    db: AsyncSession = Depends(get_db_session), current_user: TokenPayload = Depends(get_current_user),
):
    access = await _visible(employee_id, db, current_user)
    if not access.has("hr.calendar.view"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Missing permission: hr.calendar.view")
    return await CalendarService(db).employee_calendar(employee_id, start, end)


@employee_calendar_router.put("/{employee_id}/calendar-template")
async def assign_employee_template(
    employee_id: int, body: AssignTemplateIn,
    db: AsyncSession = Depends(get_db_session), current_user: TokenPayload = Depends(get_current_user),
):
    access = await _visible(employee_id, db, current_user)
    if not access.has("hr.calendar.manage"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Missing permission: hr.calendar.manage")
    await CalendarService(db).assign_template(employee_id, body.week_template_id)
    return {"employee_id": employee_id, "week_template_id": body.week_template_id}


@employee_calendar_router.put("/{employee_id}/shift")
async def assign_shift(
    employee_id: int, body: AssignShiftIn,
    db: AsyncSession = Depends(get_db_session), current_user: TokenPayload = Depends(get_current_user),
):
    access = await _visible(employee_id, db, current_user)
    if not access.has("hr.calendar.manage"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Missing permission: hr.calendar.manage")
    await CalendarService(db).assign_shift(employee_id, body.shift_pattern_id, body.anchor_date)
    return {"employee_id": employee_id, "shift_pattern_id": body.shift_pattern_id, "anchor_date": body.anchor_date.isoformat()}


@employee_calendar_router.delete("/{employee_id}/shift", status_code=204)
async def unassign_shift(
    employee_id: int,
    db: AsyncSession = Depends(get_db_session), current_user: TokenPayload = Depends(get_current_user),
):
    access = await _visible(employee_id, db, current_user)
    if not access.has("hr.calendar.manage"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Missing permission: hr.calendar.manage")
    await CalendarService(db).unassign_shift(employee_id)


@employee_calendar_router.put("/{employee_id}/calendar/{day}")
async def set_day_override(
    employee_id: int, day: date, body: EmployeeDayOverrideIn,
    db: AsyncSession = Depends(get_db_session), current_user: TokenPayload = Depends(get_current_user),
):
    access = await _visible(employee_id, db, current_user)
    if not access.has("hr.calendar.manage"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Missing permission: hr.calendar.manage")
    o = await CalendarService(db).set_employee_day_override(employee_id, day, body.day_type, body.norm_hours, body.note)
    return {"day": o.day.isoformat(), "day_type": o.day_type, "norm_hours": str(o.norm_hours), "note": o.note}


@employee_calendar_router.delete("/{employee_id}/calendar/{day}", status_code=204)
async def delete_day_override(
    employee_id: int, day: date,
    db: AsyncSession = Depends(get_db_session), current_user: TokenPayload = Depends(get_current_user),
):
    access = await _visible(employee_id, db, current_user)
    if not access.has("hr.calendar.manage"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Missing permission: hr.calendar.manage")
    await CalendarService(db).delete_employee_day_override(employee_id, day)
