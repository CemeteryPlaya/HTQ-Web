"""PMO — Project Management Office tables

Revision ID: 004
Revises: 003
Create Date: 2026-04-21

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── PMO header ───────────────────────────────────────────────────────
    op.create_table(
        "hr_pmos",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("code", sa.String(50), unique=True, nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("head_employee_id", sa.Integer, sa.ForeignKey("hr_employees.id"), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('active','suspended','closed')", name="ck_pmo_status"),
    )
    op.create_index("ix_hr_pmos_code", "hr_pmos", ["code"], unique=True)
    op.create_index("ix_hr_pmos_status", "hr_pmos", ["status"])

    # ── PMO ↔ Departments (many-to-many with role) ───────────────────────
    op.create_table(
        "hr_pmo_departments",
        sa.Column("pmo_id", sa.Integer, sa.ForeignKey("hr_pmos.id", ondelete="CASCADE"), nullable=False),
        sa.Column("department_id", sa.Integer, sa.ForeignKey("hr_departments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(20), nullable=False, server_default="owner"),
        sa.PrimaryKeyConstraint("pmo_id", "department_id"),
        sa.CheckConstraint("role IN ('owner','stakeholder','support')", name="ck_pmo_dept_role"),
    )

    # ── PMO ↔ Positions (staffing plan) ─────────────────────────────────
    op.create_table(
        "hr_pmo_positions",
        sa.Column("pmo_id", sa.Integer, sa.ForeignKey("hr_pmos.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position_id", sa.Integer, sa.ForeignKey("hr_positions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("is_required", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("headcount", sa.Integer, nullable=False, server_default="1"),
        sa.PrimaryKeyConstraint("pmo_id", "position_id"),
    )

    # ── PMO Members ──────────────────────────────────────────────────────
    op.create_table(
        "hr_pmo_members",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("pmo_id", sa.Integer, sa.ForeignKey("hr_pmos.id", ondelete="CASCADE"), nullable=False),
        sa.Column("employee_id", sa.Integer, sa.ForeignKey("hr_employees.id", ondelete="CASCADE"), nullable=False),
        sa.Column("membership_type", sa.String(20), nullable=False, server_default="permanent"),
        sa.Column("position_in_pmo", sa.String(200), nullable=True),
        sa.Column("from_date", sa.Date, nullable=False, server_default=sa.func.current_date()),
        sa.Column("to_date", sa.Date, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("pmo_id", "employee_id", name="uq_pmo_member"),
        sa.CheckConstraint(
            "membership_type IN ('permanent','assigned','consulting')",
            name="ck_pmo_member_type",
        ),
    )
    op.create_index("ix_hr_pmo_members_pmo", "hr_pmo_members", ["pmo_id"])
    op.create_index("ix_hr_pmo_members_employee", "hr_pmo_members", ["employee_id"])


def downgrade() -> None:
    op.drop_index("ix_hr_pmo_members_employee", table_name="hr_pmo_members")
    op.drop_index("ix_hr_pmo_members_pmo", table_name="hr_pmo_members")
    op.drop_table("hr_pmo_members")
    op.drop_table("hr_pmo_positions")
    op.drop_table("hr_pmo_departments")
    op.drop_index("ix_hr_pmos_status", table_name="hr_pmos")
    op.drop_index("ix_hr_pmos_code", table_name="hr_pmos")
    op.drop_table("hr_pmos")
