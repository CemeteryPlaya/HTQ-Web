"""Personnel-history API router (HR кадровая история).

CRUD over the `hr_personnel_history` table. Powers
frontend/src/pages/hr/HRHistory.tsx.

Response shape matches `HistoryRecord` in the SPA — includes resolved
display names (employee_name, *_department_name, *_position_title) so the
client doesn't need to join.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import TokenPayload, get_current_user, require_hr_write
from app.db import get_db_session
from app.models.department import Department
from app.models.employee import Employee
from app.models.personnel_history import EVENT_TYPES, PersonnelHistory
from app.models.position import Position


router = APIRouter(prefix="/personnel-history", tags=["personnel-history"])


# ─── Schemas ──────────────────────────────────────────────────────────

class PersonnelHistoryIn(BaseModel):
    employee: int
    event_type: str = "other"
    event_date: date
    from_department: int | None = None
    to_department: int | None = None
    from_position: int | None = None
    to_position: int | None = None
    order_number: str = ""
    comment: str = ""


class PersonnelHistoryOut(BaseModel):
    id: int
    employee: int
    employee_name: str
    event_type: str
    event_date: str
    from_department: int | None
    from_department_name: str | None
    to_department: int | None
    to_department_name: str | None
    from_position: int | None
    from_position_title: str | None
    to_position: int | None
    to_position_title: str | None
    order_number: str
    comment: str
    created_by_name: str | None
    created_at: str


# ─── Helpers ──────────────────────────────────────────────────────────

async def _resolve(db: AsyncSession, model, id_: int | None, label_attr: str) -> str | None:
    if id_ is None:
        return None
    obj = await db.get(model, id_)
    return getattr(obj, label_attr, None) if obj else None


async def _serialise(db: AsyncSession, ph: PersonnelHistory) -> PersonnelHistoryOut:
    employee = await db.get(Employee, ph.employee_id)
    employee_name = ""
    if employee is not None:
        first = getattr(employee, "first_name", None) or ""
        last = getattr(employee, "last_name", None) or ""
        employee_name = (f"{last} {first}".strip()
                         or getattr(employee, "display_name", None)
                         or f"#{employee.id}")
    return PersonnelHistoryOut(
        id=ph.id,
        employee=ph.employee_id,
        employee_name=employee_name,
        event_type=ph.event_type,
        event_date=ph.event_date.isoformat() if ph.event_date else "",
        from_department=ph.from_department_id,
        from_department_name=await _resolve(db, Department, ph.from_department_id, "name"),
        to_department=ph.to_department_id,
        to_department_name=await _resolve(db, Department, ph.to_department_id, "name"),
        from_position=ph.from_position_id,
        from_position_title=await _resolve(db, Position, ph.from_position_id, "title"),
        to_position=ph.to_position_id,
        to_position_title=await _resolve(db, Position, ph.to_position_id, "title"),
        order_number=ph.order_number or "",
        comment=ph.comment or "",
        # No employee_replica in hr-service yet — client shows "—" if null.
        created_by_name=None,
        created_at=ph.created_at.isoformat() if ph.created_at else "",
    )


def _validate_event_type(value: str) -> str:
    if value not in EVENT_TYPES:
        raise HTTPException(status_code=400, detail=f"event_type must be one of {EVENT_TYPES}")
    return value


# ─── Endpoints ────────────────────────────────────────────────────────

@router.get("/", response_model=list[PersonnelHistoryOut])
async def list_history(
    db: AsyncSession = Depends(get_db_session),
    _: TokenPayload = Depends(get_current_user),
):
    result = await db.execute(
        select(PersonnelHistory).order_by(PersonnelHistory.event_date.desc(), PersonnelHistory.id.desc())
    )
    rows = result.scalars().all()
    return [await _serialise(db, ph) for ph in rows]


@router.post("/", response_model=PersonnelHistoryOut, status_code=status.HTTP_201_CREATED)
async def create_history(
    body: PersonnelHistoryIn,
    db: AsyncSession = Depends(get_db_session),
    current_user: TokenPayload = Depends(require_hr_write),
):
    _validate_event_type(body.event_type)
    ph = PersonnelHistory(
        employee_id=body.employee,
        event_type=body.event_type,
        event_date=body.event_date,
        from_department_id=body.from_department,
        to_department_id=body.to_department,
        from_position_id=body.from_position,
        to_position_id=body.to_position,
        order_number=body.order_number or "",
        comment=body.comment or "",
        created_by=current_user.user_id,
    )
    db.add(ph)
    await db.commit()
    await db.refresh(ph)
    return await _serialise(db, ph)


@router.put("/{id}/", response_model=PersonnelHistoryOut)
async def update_history(
    id: int,
    body: PersonnelHistoryIn,
    db: AsyncSession = Depends(get_db_session),
    _: TokenPayload = Depends(require_hr_write),
):
    ph = await db.get(PersonnelHistory, id)
    if ph is None:
        raise HTTPException(status_code=404, detail="PersonnelHistory not found")
    _validate_event_type(body.event_type)
    ph.employee_id = body.employee
    ph.event_type = body.event_type
    ph.event_date = body.event_date
    ph.from_department_id = body.from_department
    ph.to_department_id = body.to_department
    ph.from_position_id = body.from_position
    ph.to_position_id = body.to_position
    ph.order_number = body.order_number or ""
    ph.comment = body.comment or ""
    await db.commit()
    await db.refresh(ph)
    return await _serialise(db, ph)


@router.delete("/{id}/", status_code=status.HTTP_204_NO_CONTENT)
async def delete_history(
    id: int,
    db: AsyncSession = Depends(get_db_session),
    _: TokenPayload = Depends(require_hr_write),
):
    ph = await db.get(PersonnelHistory, id)
    if ph is None:
        raise HTTPException(status_code=404, detail="PersonnelHistory not found")
    await db.delete(ph)
    await db.commit()
