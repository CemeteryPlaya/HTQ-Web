"""Task ↔ resource assignments (attach/detach employees and equipment)."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import TokenPayload, get_current_user
from app.db import get_db
from app.models.assignment import TaskAssignment
from app.schemas.gantt import AssignmentCreate, AssignmentResponse

router = APIRouter(prefix="/assignments", tags=["assignments"])


@router.get("/", response_model=list[AssignmentResponse])
async def list_assignments(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: TokenPayload = Depends(get_current_user),
    task_id: int = Query(..., description="Task to list assignments for"),
):
    stmt = select(TaskAssignment).where(TaskAssignment.task_id == task_id)
    return (await db.execute(stmt)).scalars().all()


@router.post("/", response_model=AssignmentResponse, status_code=201)
async def create_assignment(
    payload: AssignmentCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: TokenPayload = Depends(get_current_user),
):
    has_emp = payload.employee_id is not None
    has_eq = payload.equipment_id is not None
    if has_emp == has_eq:
        raise HTTPException(
            status_code=422,
            detail="Provide exactly one of employee_id or equipment_id",
        )
    obj = TaskAssignment(**payload.model_dump())
    db.add(obj)
    await db.flush()
    await db.refresh(obj)
    return obj


@router.delete("/{assignment_id}", status_code=204)
async def delete_assignment(
    assignment_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: TokenPayload = Depends(get_current_user),
):
    obj = await db.get(TaskAssignment, assignment_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Assignment not found")
    await db.delete(obj)
    await db.flush()
