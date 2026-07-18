"""Add hr_personnel_history table.

Revision ID: 006
Revises: 005
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "hr_personnel_history",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("hr_employees.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("event_type", sa.String(length=20), nullable=False, server_default="other"),
        sa.Column("event_date", sa.Date(), nullable=False),
        sa.Column("from_department_id", sa.Integer(), sa.ForeignKey("hr_departments.id", ondelete="SET NULL"), nullable=True),
        sa.Column("to_department_id", sa.Integer(), sa.ForeignKey("hr_departments.id", ondelete="SET NULL"), nullable=True),
        sa.Column("from_position_id", sa.Integer(), sa.ForeignKey("hr_positions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("to_position_id", sa.Integer(), sa.ForeignKey("hr_positions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("order_number", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("comment", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_by", sa.Integer(), nullable=True, index=True),
    )
    op.create_index("ix_hr_personnel_history_event_type", "hr_personnel_history", ["event_type"])
    op.create_index("ix_hr_personnel_history_event_date", "hr_personnel_history", ["event_date"])


def downgrade() -> None:
    op.drop_index("ix_hr_personnel_history_event_date", table_name="hr_personnel_history")
    op.drop_index("ix_hr_personnel_history_event_type", table_name="hr_personnel_history")
    op.drop_table("hr_personnel_history")
