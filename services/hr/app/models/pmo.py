"""PMO models — project management office + related join tables."""

from datetime import date

from sqlalchemy import (
    Boolean, CheckConstraint, Date, ForeignKey, Index,
    Integer, SmallInteger, String, Text, text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, BaseModel


class PMO(BaseModel):
    __tablename__ = "hr_pmos"
    __table_args__ = (
        CheckConstraint("status IN ('active','suspended','closed')", name="ck_pmo_status"),
        Index("ix_hr_pmos_code", "code", unique=True),
        Index("ix_hr_pmos_status", "status"),
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    head_employee_id: Mapped[int | None] = mapped_column(ForeignKey("hr_employees.id"))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")

    def __repr__(self) -> str:
        return f"<PMO(id={self.id}, code='{self.code}', status='{self.status}')>"


class PMODepartment(Base):
    __tablename__ = "hr_pmo_departments"
    __table_args__ = (
        CheckConstraint("role IN ('owner','stakeholder','support')", name="ck_pmo_dept_role"),
    )

    pmo_id: Mapped[int] = mapped_column(
        ForeignKey("hr_pmos.id", ondelete="CASCADE"), primary_key=True
    )
    department_id: Mapped[int] = mapped_column(
        ForeignKey("hr_departments.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="owner")


class PMOPosition(Base):
    __tablename__ = "hr_pmo_positions"

    pmo_id: Mapped[int] = mapped_column(
        ForeignKey("hr_pmos.id", ondelete="CASCADE"), primary_key=True
    )
    position_id: Mapped[int] = mapped_column(
        ForeignKey("hr_positions.id", ondelete="CASCADE"), primary_key=True
    )
    is_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    headcount: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class PMOMember(Base):
    __tablename__ = "hr_pmo_members"
    __table_args__ = (
        CheckConstraint(
            "membership_type IN ('permanent','assigned','consulting')",
            name="ck_pmo_member_type",
        ),
        CheckConstraint(
            "allocation_percent BETWEEN 0 AND 100",
            name="ck_pmo_member_allocation_pct",
        ),
        CheckConstraint(
            "to_date IS NULL OR to_date >= from_date",
            name="ck_pmo_member_dates",
        ),
        Index("ix_hr_pmo_members_pmo", "pmo_id"),
        Index("ix_hr_pmo_members_employee", "employee_id"),
        Index(
            "ux_hr_pmo_members_open_employee",
            "pmo_id",
            "employee_id",
            unique=True,
            postgresql_where=text("to_date IS NULL"),
        ),
        Index(
            "ux_hr_pmo_members_open_primary",
            "pmo_id",
            unique=True,
            postgresql_where=text("is_primary AND to_date IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pmo_id: Mapped[int] = mapped_column(ForeignKey("hr_pmos.id", ondelete="CASCADE"), nullable=False)
    employee_id: Mapped[int] = mapped_column(ForeignKey("hr_employees.id", ondelete="CASCADE"), nullable=False)
    membership_type: Mapped[str] = mapped_column(String(20), nullable=False, default="permanent")
    position_in_pmo: Mapped[str | None] = mapped_column(String(200))
    from_date: Mapped[date] = mapped_column(Date, nullable=False)
    to_date: Mapped[date | None] = mapped_column(Date)
    allocation_percent: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=100)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
