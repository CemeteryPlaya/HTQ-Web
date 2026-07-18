"""Personnel history (HR кадровая история) model.

One row per HR event: hire, dismiss, transfer, promotion, demotion, other.
Drives the /hr/history SPA page (frontend/src/pages/hr/HRHistory.tsx).
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import Date, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel


EVENT_TYPES = ("hired", "dismissed", "transfer", "promotion", "demotion", "other")


class PersonnelHistory(BaseModel):
    __tablename__ = "hr_personnel_history"

    employee_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("hr_employees.id", ondelete="CASCADE"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(20), default="other", index=True)
    event_date: Mapped[date] = mapped_column(Date, index=True)

    from_department_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("hr_departments.id", ondelete="SET NULL"), nullable=True
    )
    to_department_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("hr_departments.id", ondelete="SET NULL"), nullable=True
    )
    from_position_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("hr_positions.id", ondelete="SET NULL"), nullable=True
    )
    to_position_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("hr_positions.id", ondelete="SET NULL"), nullable=True
    )

    order_number: Mapped[str] = mapped_column(String(64), default="")
    comment: Mapped[str] = mapped_column(Text, default="")

    # Recorded user_id of the HR who created the record (no FK — user lives
    # in user-service, replicated read-only via task_users elsewhere; we
    # don't have that table here so just store the int).
    created_by: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

    def __repr__(self) -> str:
        return f"<PersonnelHistory(id={self.id}, employee_id={self.employee_id}, event={self.event_type})>"
