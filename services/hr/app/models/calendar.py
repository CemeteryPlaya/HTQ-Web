"""Production-calendar models: week templates, date overrides, assignments."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Boolean, Date, ForeignKey, JSON, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel


class WeekTemplate(BaseModel):
    __tablename__ = "hr_week_templates"

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    days: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class CalendarDay(BaseModel):
    __tablename__ = "hr_calendar_days"

    day: Mapped[date] = mapped_column(Date, unique=True, nullable=False, index=True)
    day_type: Mapped[str] = mapped_column(String(16), nullable=False)
    norm_hours: Mapped[Decimal] = mapped_column(Numeric(4, 2), nullable=False, default=0)
    note: Mapped[str | None] = mapped_column(String(255))


class EmployeeWeekTemplate(BaseModel):
    __tablename__ = "hr_employee_week_template"

    employee_id: Mapped[int] = mapped_column(
        ForeignKey("hr_employees.id", ondelete="CASCADE"), unique=True, index=True
    )
    week_template_id: Mapped[int] = mapped_column(
        ForeignKey("hr_week_templates.id", ondelete="CASCADE")
    )


class ShiftPattern(BaseModel):
    __tablename__ = "hr_shift_patterns"

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    # [{"type": "work"|"off", "hours": <number>}, ...]; len = cycle length
    slots: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    holidays_off: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class EmployeeShiftAssignment(BaseModel):
    __tablename__ = "hr_employee_shift_assignment"

    employee_id: Mapped[int] = mapped_column(
        ForeignKey("hr_employees.id", ondelete="CASCADE"), unique=True, index=True
    )
    shift_pattern_id: Mapped[int] = mapped_column(
        ForeignKey("hr_shift_patterns.id", ondelete="CASCADE")
    )
    anchor_date: Mapped[date] = mapped_column(Date, nullable=False)


class EmployeeDayOverride(BaseModel):
    __tablename__ = "hr_employee_day_override"
    __table_args__ = (
        __import__("sqlalchemy").UniqueConstraint("employee_id", "day", name="uq_hr_emp_day_override"),
    )

    employee_id: Mapped[int] = mapped_column(
        ForeignKey("hr_employees.id", ondelete="CASCADE"), index=True
    )
    day: Mapped[date] = mapped_column(Date, nullable=False)
    day_type: Mapped[str] = mapped_column(String(16), nullable=False)
    norm_hours: Mapped[Decimal] = mapped_column(Numeric(4, 2), nullable=False, default=0)
    note: Mapped[str | None] = mapped_column(String(255))
