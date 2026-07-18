from datetime import date
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import ProductionDay

async def calculate_due_date(
    session: AsyncSession, start_date: date, working_days: int
) -> date:
    # SELECT working_days_since_epoch FROM production_days WHERE date = :start_date
    row = await session.execute(select(ProductionDay.working_days_since_epoch)
                                .where(ProductionDay.date == start_date))
    start_wd = row.scalar_one()
    target_wd = start_wd + working_days
    # Обратный lookup: найти date где working_days_since_epoch == target_wd
    row = await session.execute(select(ProductionDay.date)
                                .where(ProductionDay.working_days_since_epoch == target_wd)
                                .where(ProductionDay.day_type.in_(("working", "short")))
                                .order_by(ProductionDay.date.asc()).limit(1))
    return row.scalar_one()
