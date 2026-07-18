"""Employee model."""

from __future__ import annotations

from datetime import date

from sqlalchemy import Date, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel


class Employee(BaseModel):
    __tablename__ = "hr_employees"

    user_id: Mapped[int | None] = mapped_column(unique=True)  # link to User Service
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    middle_name: Mapped[str | None] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    phone: Mapped[str | None] = mapped_column(String(20))
    department_id: Mapped[int] = mapped_column(ForeignKey("hr_departments.id"))
    position_id: Mapped[int] = mapped_column(ForeignKey("hr_positions.id"))
    hire_date: Mapped[date] = mapped_column(Date, nullable=False)
    termination_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="active")  # active | inactive | terminated
    avatar_url: Mapped[str | None] = mapped_column(String(500))
    bio: Mapped[str | None] = mapped_column(Text)
    is_deleted: Mapped[bool] = mapped_column(default=False)  # soft delete

    # Relationships
    department: Mapped[Department] = relationship(  # noqa: F821
        "Department",
        back_populates="employees",
        foreign_keys=[department_id],
    )
    position: Mapped[Position] = relationship("Position", foreign_keys=[position_id])  # noqa: F821
    managed_department: Mapped[Department | None] = relationship(  # noqa: F821
        "Department",
        back_populates="manager",
        foreign_keys="Department.manager_id",
    )
    time_entries: Mapped[list[TimeEntry]] = relationship(  # noqa: F821
        "TimeEntry", back_populates="employee"
    )
    documents: Mapped[list[Document]] = relationship(  # noqa: F821
        "Document",
        back_populates="employee",
        foreign_keys="Document.employee_id",
    )

    def __repr__(self) -> str:
        return f"<Employee(id={self.id}, email='{self.email}', status='{self.status}')>"
