"""Application (отклик кандидата) model."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel


class Application(BaseModel):
    __tablename__ = "hr_applications"

    vacancy_id: Mapped[int] = mapped_column(ForeignKey("hr_vacancies.id"))
    candidate_name: Mapped[str] = mapped_column(String(255), nullable=False)
    candidate_email: Mapped[str] = mapped_column(String(255), nullable=False)
    candidate_phone: Mapped[str | None] = mapped_column(String(20))
    resume_url: Mapped[str | None] = mapped_column(String(500))
    cover_letter: Mapped[str | None] = mapped_column(Text)
    # new | reviewed | interview | offer | rejected | hired
    status: Mapped[str] = mapped_column(String(30), default="new")
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    notes: Mapped[str | None] = mapped_column(Text)

    vacancy: Mapped[Vacancy] = relationship("Vacancy", back_populates="applications")  # noqa: F821

    def __repr__(self) -> str:
        return f"<Application(id={self.id}, candidate='{self.candidate_name}', status='{self.status}')>"
