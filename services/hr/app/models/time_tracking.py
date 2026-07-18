"""TimeEntry model for work-time tracking."""

from __future__ import annotations

from datetime import date, time

from sqlalchemy import Date, ForeignKey, Integer, String, Text, Time, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel


class TimeEntry(BaseModel):
    __tablename__ = "hr_time_entries"
    __table_args__ = (
        UniqueConstraint("employee_id", "date", "start_time", name="uq_employee_time_entry"),
    )

    employee_id: Mapped[int] = mapped_column(ForeignKey("hr_employees.id"))
    date: Mapped[date] = mapped_column(Date, nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    break_minutes: Mapped[int] = mapped_column(Integer, default=0)
    description: Mapped[str | None] = mapped_column(Text)
    project: Mapped[str | None] = mapped_column(String(255))
    task: Mapped[str | None] = mapped_column(String(255))

    employee: Mapped[Employee] = relationship("Employee", back_populates="time_entries")  # noqa: F821

    def __repr__(self) -> str:
        return f"<TimeEntry(id={self.id}, employee_id={self.employee_id}, date={self.date})>"
