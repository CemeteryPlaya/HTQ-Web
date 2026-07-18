"""Time tracking API router."""

from datetime import date

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db_session
from app.auth.dependencies import get_current_user, TokenPayload
from app.schemas.time_tracking import (
    TimeEntryCreate,
    TimeEntryUpdate,
    TimeEntryOut,
    DailyReport,
    WeeklyReport,
    MonthlyReport,
)
from app.schemas.common import PaginatedResponse
from app.services.time_service import TimeService

router = APIRouter(prefix="/time-tracking", tags=["time-tracking"])


def _svc(db: AsyncSession = Depends(get_db_session)) -> TimeService:
    return TimeService(db)


@router.get("/", response_model=PaginatedResponse[TimeEntryOut])
async def list_root(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=200),
    svc: TimeService = Depends(_svc),
    _: TokenPayload = Depends(get_current_user),
):
    """Root listing — alias of /entries/.

    The HR Time Tracking page hits the prefix root directly, so we mirror the
    paginated entry list here. Existing /entries/ remains for backward compat.
    """
    items, total = await svc.list_entries(page=page, limit=limit)
    pages = (total + limit - 1) // limit
    return PaginatedResponse(items=items, total=total, page=page, pages=pages, limit=limit)


@router.get("/entries/", response_model=PaginatedResponse[TimeEntryOut])
async def list_entries(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=200),
    svc: TimeService = Depends(_svc),
    _: TokenPayload = Depends(get_current_user),
):
    items, total = await svc.list_entries(page=page, limit=limit)
    pages = (total + limit - 1) // limit
    return PaginatedResponse(items=items, total=total, page=page, pages=pages, limit=limit)


@router.post("/entries/", response_model=TimeEntryOut, status_code=status.HTTP_201_CREATED)
async def create_entry(
    body: TimeEntryCreate,
    svc: TimeService = Depends(_svc),
    _: TokenPayload = Depends(get_current_user),
):
    return await svc.create_entry(body)


@router.put("/entries/{id}/", response_model=TimeEntryOut)
async def update_entry(
    id: int,
    body: TimeEntryUpdate,
    svc: TimeService = Depends(_svc),
    _: TokenPayload = Depends(get_current_user),
):
    return await svc.update_entry(id, body)


@router.delete("/entries/{id}/", status_code=status.HTTP_204_NO_CONTENT)
async def delete_entry(
    id: int,
    svc: TimeService = Depends(_svc),
    _: TokenPayload = Depends(get_current_user),
):
    await svc.delete_entry(id)


@router.get("/reports/daily", response_model=DailyReport)
async def daily_report(
    employee_id: int = Query(...),
    date: date = Query(default_factory=date.today),
    svc: TimeService = Depends(_svc),
    _: TokenPayload = Depends(get_current_user),
):
    return await svc.daily_report(employee_id, date)


@router.get("/reports/weekly", response_model=WeeklyReport)
async def weekly_report(
    employee_id: int = Query(...),
    week_start: date = Query(..., description="Monday of the week (YYYY-MM-DD)"),
    svc: TimeService = Depends(_svc),
    _: TokenPayload = Depends(get_current_user),
):
    return await svc.weekly_report(employee_id, week_start)


@router.get("/reports/monthly", response_model=MonthlyReport)
async def monthly_report(
    employee_id: int = Query(...),
    year: int = Query(..., ge=2000, le=2100),
    month: int = Query(..., ge=1, le=12),
    svc: TimeService = Depends(_svc),
    _: TokenPayload = Depends(get_current_user),
):
    return await svc.monthly_report(employee_id, year, month)
