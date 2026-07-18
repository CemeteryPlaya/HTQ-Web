"""Task sequence and production calendar models."""

from datetime import date

from sqlalchemy import Date, Integer, String, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel


class TaskSequence(BaseModel):
    """Atomic counter for generating unique task keys.
    
    Uses select_for_update() for race condition prevention.
    """

    __tablename__ = "task_sequence"

    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    current_value: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    @classmethod
    async def get_next_value(cls, session: AsyncSession, prefix: str = "TASK") -> int:
        """Atomically increment and return the next sequence value."""
        from sqlalchemy import select
        
        result = await session.execute(
            select(cls).where(cls.name == prefix).with_for_update()
        )
        sequence = result.scalar_one_or_none()
        
        if not sequence:
            sequence = cls(name=prefix, current_value=0)
            session.add(sequence)
            await session.flush()
        
        sequence.current_value += 1
        await session.flush()
        return sequence.current_value


class ProductionDay(BaseModel):
    """Production calendar with working day tracking.
    
    Used for O(1) deadline calculation using cumulative working days.
    """

    __tablename__ = "production_days"

    date: Mapped[date] = mapped_column(Date, unique=True, nullable=False, index=True)
    day_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="working"
    )  # working, weekend, holiday, short
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    working_days_since_epoch: Mapped[int] = mapped_column(
        Integer, nullable=False, index=True
    )

    @classmethod
    async def get_date_by_working_days(
        cls, session: AsyncSession, start_date: date, working_days: int
    ) -> date | None:
        """Calculate due date based on working days from start date.
        
        Uses cumulative working days for O(1) lookup.
        """
        result = await session.execute(
            select(cls).where(
                cls.date >= start_date,
                cls.day_type.in_(("working", "short")),
                cls.working_days_since_epoch
                >= (
                    select(cls.working_days_since_epoch)
                    .where(cls.date == start_date)
                    .scalar_subquery()
                ) + working_days - 1,
            ).order_by(cls.date).limit(1)
        )
        day = result.scalar_one_or_none()
        return day.date if day else None
