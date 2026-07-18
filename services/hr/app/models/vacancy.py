"""Vacancy model."""

from __future__ import annotations

from datetime import date

from sqlalchemy import Date, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel


class Vacancy(BaseModel):
    __tablename__ = "hr_vacancies"

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    department_id: Mapped[int] = mapped_column(ForeignKey("hr_departments.id"))
    position_id: Mapped[int] = mapped_column(ForeignKey("hr_positions.id"))
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    requirements: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(20), default="open")  # open | closed | on_hold
    opened_at: Mapped[date] = mapped_column(Date, server_default=func.current_date())
    closed_at: Mapped[date | None] = mapped_column(Date)
    assigned_recruiter_id: Mapped[int | None] = mapped_column(ForeignKey("hr_employees.id"))

    applications: Mapped[list[Application]] = relationship("Application", back_populates="vacancy")  # noqa: F821

    def __repr__(self) -> str:
        return f"<Vacancy(id={self.id}, title='{self.title}', status='{self.status}')>"
