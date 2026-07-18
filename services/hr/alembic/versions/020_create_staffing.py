"""Create hr_staffing_positions.

Revision ID: 020_create_staffing
Revises: 019_create_shift_schedules
Create Date: 2026-05-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "020_create_staffing"
down_revision = "019_create_shift_schedules"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "hr_staffing_positions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("position_id", sa.Integer(), sa.ForeignKey("hr_positions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("department_id", sa.Integer(), sa.ForeignKey("hr_departments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("grade", sa.Integer(), nullable=True),
        sa.Column("headcount", sa.Numeric(5, 2), nullable=False, server_default="1"),
        sa.Column("salary", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("note", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_hr_staffing_position", "hr_staffing_positions", ["position_id"])
    op.create_index("ix_hr_staffing_department", "hr_staffing_positions", ["department_id"])


def downgrade() -> None:
    op.drop_table("hr_staffing_positions")
