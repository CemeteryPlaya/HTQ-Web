"""Department model with ltree path."""

from __future__ import annotations

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel


class Department(BaseModel):
    __tablename__ = "hr_departments"
    __table_args__ = (
        Index("ix_hr_departments_path", "path"),
    )

    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    # ltree stored as plain text (requires ltree extension in PG)
    path: Mapped[str] = mapped_column(String(500), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    manager_id: Mapped[int | None] = mapped_column(ForeignKey("hr_employees.id", use_alter=True))
    is_active: Mapped[bool] = mapped_column(default=True)
    unit_type: Mapped[str] = mapped_column(String(20), nullable=False, default="department")

    # Relationships (populated after Employee is defined)
    employees: Mapped[list[Employee]] = relationship(  # noqa: F821
        "Employee",
        back_populates="department",
        foreign_keys="Employee.department_id",
    )
    manager: Mapped[Employee | None] = relationship(  # noqa: F821
        "Employee",
        back_populates="managed_department",
        foreign_keys="Department.manager_id",
    )
    # Positions in this department — eager-loaded by GET /departments/ via
    # selectinload. Read-only here; positions are CRUD'd through their own router.
    positions: Mapped[list["Position"]] = relationship(  # noqa: F821
        "Position",
        primaryjoin="Department.id == Position.department_id",
        foreign_keys="Position.department_id",
        viewonly=True,
        order_by="Position.weight",
    )

    def __repr__(self) -> str:
        return f"<Department(id={self.id}, name='{self.name}', path='{self.path}')>"
