"""Staffing-table model: independent budgeted-headcount lines."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel


class StaffingPosition(BaseModel):
    __tablename__ = "hr_staffing_positions"

    position_id: Mapped[int] = mapped_column(
        ForeignKey("hr_positions.id", ondelete="CASCADE"), index=True
    )
    department_id: Mapped[int] = mapped_column(
        ForeignKey("hr_departments.id", ondelete="CASCADE"), index=True
    )
    grade: Mapped[int | None] = mapped_column(Integer)
    headcount: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=1)
    salary: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    note: Mapped[str | None] = mapped_column(String(255))
