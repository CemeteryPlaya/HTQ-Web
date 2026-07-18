"""Shareable links — one-time/time-limited public org-chart access

Revision ID: 005
Revises: 004
Create Date: 2026-04-21

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")  # for gen_random_uuid()

    op.create_table(
        "hr_shareable_links",
        sa.Column("id", sa.UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("token", sa.String(64), unique=True, nullable=False),
        # No FK — user_id comes from User Service (cross-service; avoid hard dependency)
        sa.Column("created_by_user_id", sa.Integer, nullable=False),
        sa.Column("label", sa.String(200), nullable=True),
        sa.Column("max_level", sa.Integer, nullable=False, server_default="3"),
        # null = entire company; JSON array of department IDs
        sa.Column("visible_units", sa.JSON, nullable=True),
        sa.Column(
            "link_type",
            sa.String(30),
            nullable=False,
            server_default="one_time",
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("opened_by_ip", sa.String(45), nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint(
            "link_type IN ('one_time','time_limited','permanent_with_expiry')",
            name="ck_link_type",
        ),
        sa.CheckConstraint("max_level >= 1", name="ck_link_max_level"),
    )
    op.create_index("ix_shareable_links_token", "hr_shareable_links", ["token"], unique=True)
    op.create_index("ix_shareable_links_user", "hr_shareable_links", ["created_by_user_id"])
    op.create_index("ix_shareable_links_active", "hr_shareable_links", ["is_active"])


def downgrade() -> None:
    op.drop_index("ix_shareable_links_active", table_name="hr_shareable_links")
    op.drop_index("ix_shareable_links_user", table_name="hr_shareable_links")
    op.drop_index("ix_shareable_links_token", table_name="hr_shareable_links")
    op.drop_table("hr_shareable_links")
