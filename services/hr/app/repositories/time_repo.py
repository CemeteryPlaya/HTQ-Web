"""Time tracking repository."""

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.time_tracking import TimeEntry
from app.repositories.base_repo import BaseRepository


class TimeRepository(BaseRepository[TimeEntry]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(TimeEntry, session)

    async def get_entries_for_employee(
        self,
        employee_id: int,
        date_from: date,
        date_to: date,
    ) -> list[TimeEntry]:
        stmt = (
            select(TimeEntry)
            .where(
                TimeEntry.employee_id == employee_id,
                TimeEntry.date >= date_from,
                TimeEntry.date <= date_to,
            )
            .order_by(TimeEntry.date, TimeEntry.start_time)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_daily(self, employee_id: int, day: date) -> list[TimeEntry]:
        return await self.get_entries_for_employee(employee_id, day, day)

    async def get_weekly(self, employee_id: int, week_start: date) -> list[TimeEntry]:
        week_end = week_start + timedelta(days=6)
        return await self.get_entries_for_employee(employee_id, week_start, week_end)

    async def get_monthly(self, employee_id: int, year: int, month: int) -> list[TimeEntry]:
        from calendar import monthrange
        _, last_day = monthrange(year, month)
        return await self.get_entries_for_employee(
            employee_id, date(year, month, 1), date(year, month, last_day)
        )
