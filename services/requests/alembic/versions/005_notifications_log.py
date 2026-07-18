"""notifications log

Revision ID: 005
Revises: 004
Create Date: 2026-05-24
"""
from alembic import op
import sqlalchemy as sa

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "request_notifications_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("request_id", sa.Integer(), sa.ForeignKey("request_instances.id", ondelete="CASCADE"), nullable=False),
        sa.Column("recipient_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("channel", sa.String(length=10), nullable=False, server_default="bot"),
        sa.Column("dedup_key", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("dedup_key", name="uq_request_notifications_dedup"),
    )
    op.create_index("ix_request_notifications_request_id", "request_notifications_log", ["request_id"])
    op.create_index("ix_request_notifications_recipient_id", "request_notifications_log", ["recipient_id"])
    op.create_index("ix_request_notifications_created_at", "request_notifications_log", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_request_notifications_created_at", table_name="request_notifications_log")
    op.drop_index("ix_request_notifications_recipient_id", table_name="request_notifications_log")
    op.drop_index("ix_request_notifications_request_id", table_name="request_notifications_log")
    op.drop_table("request_notifications_log")
