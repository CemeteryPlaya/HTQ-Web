"""Time tracking service."""

from datetime import date, timedelta

import structlog
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.time_tracking import TimeEntry
from app.repositories.time_repo import TimeRepository
from app.schemas.time_tracking import (
    TimeEntryCreate,
    TimeEntryUpdate,
    DailyReport,
    WeeklyReport,
    MonthlyReport,
    TimeEntryOut,
)

logger = structlog.get_logger()


def _minutes(entry: TimeEntry) -> int:
    start = entry.start_time.hour * 60 + entry.start_time.minute
    end = entry.end_time.hour * 60 + entry.end_time.minute
    return max(0, end - start - entry.break_minutes)


class TimeService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = TimeRepository(session)

    async def list_entries(self, *, page: int = 1, limit: int = 20) -> tuple[list[TimeEntry], int]:
        offset = (page - 1) * limit
        items, total = await self.repo.list(offset=offset, limit=limit, order_by="date", order="desc")
        return list(items), total

    async def get_entry(self, id: int) -> TimeEntry:
        entry = await self.repo.get(id)
        if not entry:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Time entry not found")
        return entry

    async def create_entry(self, data: TimeEntryCreate) -> TimeEntry:
        entry = await self.repo.create(data.model_dump())
        logger.info("time_entry_created", entry_id=entry.id, employee_id=data.employee_id)
        return entry

    async def update_entry(self, id: int, data: TimeEntryUpdate) -> TimeEntry:
        entry = await self.get_entry(id)
        updated = await self.repo.update(entry, data.model_dump(exclude_none=True))
        logger.info("time_entry_updated", entry_id=id)
        return updated

    async def delete_entry(self, id: int) -> None:
        entry = await self.get_entry(id)
        await self.repo.delete(entry)
        logger.info("time_entry_deleted", entry_id=id)

    async def daily_report(self, employee_id: int, day: date) -> DailyReport:
        entries = await self.repo.get_daily(employee_id, day)
        total = sum(_minutes(e) for e in entries)
        return DailyReport(
            date=day,
            employee_id=employee_id,
            total_minutes=total,
            entries=[TimeEntryOut.model_validate(e) for e in entries],
        )

    async def weekly_report(self, employee_id: int, week_start: date) -> WeeklyReport:
        week_end = week_start + timedelta(days=6)
        entries = await self.repo.get_weekly(employee_id, week_start)

        # Group by day
        days_map: dict[date, list[TimeEntry]] = {}
        for e in entries:
            days_map.setdefault(e.date, []).append(e)

        daily: list[DailyReport] = []
        for i in range(7):
            day = week_start + timedelta(days=i)
            day_entries = days_map.get(day, [])
            total = sum(_minutes(e) for e in day_entries)
            daily.append(DailyReport(
                date=day,
                employee_id=employee_id,
                total_minutes=total,
                entries=[TimeEntryOut.model_validate(e) for e in day_entries],
            ))

        return WeeklyReport(
            week_start=week_start,
            week_end=week_end,
            employee_id=employee_id,
            total_minutes=sum(d.total_minutes for d in daily),
            daily=daily,
        )

    async def monthly_report(self, employee_id: int, year: int, month: int) -> MonthlyReport:
        entries = await self.repo.get_monthly(employee_id, year, month)
        total = sum(_minutes(e) for e in entries)

        # Group by ISO week
        weeks: dict[date, list[TimeEntry]] = {}
        for e in entries:
            week_start = e.date - timedelta(days=e.date.weekday())
            weeks.setdefault(week_start, []).append(e)

        weekly_reports: list[WeeklyReport] = []
        for ws in sorted(weeks):
            week_entries = weeks[ws]
            week_end = ws + timedelta(days=6)
            weekly_reports.append(WeeklyReport(
                week_start=ws,
                week_end=week_end,
                employee_id=employee_id,
                total_minutes=sum(_minutes(e) for e in week_entries),
                daily=[],
            ))

        return MonthlyReport(
            year=year,
            month=month,
            employee_id=employee_id,
            total_minutes=total,
            weekly=weekly_reports,
        )
