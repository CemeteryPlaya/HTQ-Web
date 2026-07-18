"""stats daily rollup

Revision ID: 006
Revises: 005
Create Date: 2026-05-25
"""
from alembic import op
import sqlalchemy as sa

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "request_stats_daily",
        sa.Column("date", sa.Date(), nullable=False),
        # project_id=0 is the sentinel for "no project" (NULL can't sit in a
        # PG composite primary key). The runtime substitutes 0 on UPSERT.
        sa.Column("project_id", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("template_id", sa.Integer(), nullable=False),
        sa.Column("created", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("approved", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rejected", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cancelled", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sum_approved_amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("time_to_decision_seconds_sum", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("date", "project_id", "template_id", name="pk_request_stats_daily"),
    )
    op.create_index("ix_request_stats_daily_date", "request_stats_daily", ["date"])


def downgrade() -> None:
    op.drop_index("ix_request_stats_daily_date", table_name="request_stats_daily")
    op.drop_table("request_stats_daily")
