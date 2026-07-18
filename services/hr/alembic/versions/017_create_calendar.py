"""Create production-calendar tables + seed default 5/2 week template.

Revision ID: 017_create_calendar
Revises: 016_merge_card_keys
Create Date: 2026-05-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "017_create_calendar"
down_revision = "016_merge_card_keys"
branch_labels = None
depends_on = None

_DEFAULT_DAYS = {
    "0": {"type": "working", "hours": 8},
    "1": {"type": "working", "hours": 8},
    "2": {"type": "working", "hours": 8},
    "3": {"type": "working", "hours": 8},
    "4": {"type": "working", "hours": 8},
    "5": {"type": "weekend", "hours": 0},
    "6": {"type": "weekend", "hours": 0},
}


def upgrade() -> None:
    op.create_table(
        "hr_week_templates",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("days", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "hr_calendar_days",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("day_type", sa.String(16), nullable=False),
        sa.Column("norm_hours", sa.Numeric(4, 2), nullable=False, server_default="0"),
        sa.Column("note", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_unique_constraint("uq_hr_calendar_days_day", "hr_calendar_days", ["day"])
    op.create_index("ix_hr_calendar_days_day", "hr_calendar_days", ["day"])
    op.create_table(
        "hr_employee_week_template",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("hr_employees.id", ondelete="CASCADE"), nullable=False),
        sa.Column("week_template_id", sa.Integer(), sa.ForeignKey("hr_week_templates.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_unique_constraint("uq_hr_emp_week_tmpl_employee", "hr_employee_week_template", ["employee_id"])
    op.create_index("ix_hr_emp_week_tmpl_employee", "hr_employee_week_template", ["employee_id"])

    op.bulk_insert(
        sa.table(
            "hr_week_templates",
            sa.column("name", sa.String),
            sa.column("is_default", sa.Boolean),
            sa.column("days", sa.JSON),
        ),
        [{"name": "Стандарт 5/2", "is_default": True, "days": _DEFAULT_DAYS}],
    )


def downgrade() -> None:
    op.drop_table("hr_employee_week_template")
    op.drop_table("hr_calendar_days")
    op.drop_table("hr_week_templates")
