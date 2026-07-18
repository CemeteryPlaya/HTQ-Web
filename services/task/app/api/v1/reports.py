"""Gantt report endpoints: task report Gantt + resource-planning Gantt."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import TokenPayload, get_current_user
from app.db import get_db
from app.schemas.gantt import ReportsGanttResponse, ResourceGanttResponse
from app.services import gantt_service

router = APIRouter(prefix="/reports", tags=["reports-gantt"])


def _csv_ints(value: str | None) -> list[int] | None:
    if not value:
        return None
    return [int(x) for x in value.split(",") if x.strip().isdigit()]


def _csv(value: str | None) -> list[str] | None:
    if not value:
        return None
    return [x.strip() for x in value.split(",") if x.strip()]


@router.get("/gantt", response_model=ReportsGanttResponse)
async def reports_gantt(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: TokenPayload = Depends(get_current_user),
    ids: str | None = Query(None, description="Comma-separated task ids to include"),
    status: str | None = Query(None, description="Comma-separated statuses filter"),
):
    """Flat Gantt for selected tasks (report on planned/actual dates)."""
    return await gantt_service.reports_gantt(db, _csv_ints(ids), _csv(status))


@router.get("/resource-gantt", response_model=ResourceGanttResponse)
async def resource_gantt(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: TokenPayload = Depends(get_current_user),
    dt_from: date = Query(..., alias="from", description="Window start (YYYY-MM-DD)"),
    dt_to: date = Query(..., alias="to", description="Window end (YYYY-MM-DD)"),
    kinds: str = Query("employee,equipment", description="employee,equipment"),
    department_id: int | None = Query(None),
    search: str | None = Query(None),
):
    """Resource-load Gantt: tasks grouped by employee and equipment rows."""
    kind_set = {k.strip() for k in kinds.split(",") if k.strip()}
    return await gantt_service.resource_gantt(
        db, dt_from, dt_to, kind_set, department_id, search
    )
