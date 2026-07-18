"""EmployeeCard — 1:1 Т-2 scalar fields (financial / personal / certs)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel


class EmployeeCard(BaseModel):
    __tablename__ = "hr_employee_card"

    employee_id: Mapped[int] = mapped_column(
        ForeignKey("hr_employees.id", ondelete="CASCADE"), unique=True, index=True
    )
    salary: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    bonus: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    bank_account: Mapped[str | None] = mapped_column(String(64))
    passport_data: Mapped[str | None] = mapped_column(Text)
    inn: Mapped[str | None] = mapped_column(String(20))
    birth_date: Mapped[date | None] = mapped_column(Date)
    birth_place: Mapped[str | None] = mapped_column(String(255))
    citizenship: Mapped[str | None] = mapped_column(String(100))
    sro_permit_number: Mapped[str | None] = mapped_column(String(100))
    sro_permit_expiry: Mapped[date | None] = mapped_column(Date)
    safety_cert_number: Mapped[str | None] = mapped_column(String(100))
    safety_cert_expiry: Mapped[date | None] = mapped_column(Date)

    def __repr__(self) -> str:
        return f"<EmployeeCard(employee_id={self.employee_id})>"
