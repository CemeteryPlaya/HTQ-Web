"""Create cyclic shift schedule tables.

Revision ID: 019_create_shift_schedules
Revises: 018_merge_calendar_keys
Create Date: 2026-05-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "019_create_shift_schedules"
down_revision = "018_merge_calendar_keys"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "hr_shift_patterns",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("slots", sa.JSON(), nullable=False),
        sa.Column("holidays_off", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "hr_employee_shift_assignment",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("hr_employees.id", ondelete="CASCADE"), nullable=False),
        sa.Column("shift_pattern_id", sa.Integer(), sa.ForeignKey("hr_shift_patterns.id", ondelete="CASCADE"), nullable=False),
        sa.Column("anchor_date", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_unique_constraint("uq_hr_emp_shift_employee", "hr_employee_shift_assignment", ["employee_id"])
    op.create_index("ix_hr_emp_shift_employee", "hr_employee_shift_assignment", ["employee_id"])
    op.create_table(
        "hr_employee_day_override",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("hr_employees.id", ondelete="CASCADE"), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("day_type", sa.String(16), nullable=False),
        sa.Column("norm_hours", sa.Numeric(4, 2), nullable=False, server_default="0"),
        sa.Column("note", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_unique_constraint("uq_hr_emp_day_override", "hr_employee_day_override", ["employee_id", "day"])
    op.create_index("ix_hr_emp_day_override_employee", "hr_employee_day_override", ["employee_id"])


def downgrade() -> None:
    op.drop_table("hr_employee_day_override")
    op.drop_table("hr_employee_shift_assignment")
    op.drop_table("hr_shift_patterns")
