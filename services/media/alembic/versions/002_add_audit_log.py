"""Add audit_log table for media-service

Revision ID: 0002_audit_log
Revises: 644483c8e978
Create Date: 2026-04-24 07:10:00.000000

The initial migration missed the audit_log table (model existed but wasn't
picked up by autogenerate because of schema ordering). This file creates
it explicitly so ``services/audit.record_action`` stops raising
UndefinedTableError — which currently blocks any upload (avatar, user files).
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0002_audit_log"
down_revision: Union[str, None] = "644483c8e978"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("resource_type", sa.String(length=100), nullable=False),
        sa.Column("resource_id", sa.String(length=100), nullable=True),
        sa.Column("changes", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("correlation_id", sa.String(length=36), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="media",
    )
    op.create_index(
        op.f("ix_media_audit_log_action"),
        "audit_log",
        ["action"],
        unique=False,
        schema="media",
    )
    op.create_index(
        op.f("ix_media_audit_log_correlation_id"),
        "audit_log",
        ["correlation_id"],
        unique=False,
        schema="media",
    )
    op.create_index(
        op.f("ix_media_audit_log_created_at"),
        "audit_log",
        ["created_at"],
        unique=False,
        schema="media",
    )
    op.create_index(
        op.f("ix_media_audit_log_resource_id"),
        "audit_log",
        ["resource_id"],
        unique=False,
        schema="media",
    )
    op.create_index(
        op.f("ix_media_audit_log_user_id"),
        "audit_log",
        ["user_id"],
        unique=False,
        schema="media",
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_media_audit_log_user_id"), table_name="audit_log", schema="media")
    op.drop_index(op.f("ix_media_audit_log_resource_id"), table_name="audit_log", schema="media")
    op.drop_index(op.f("ix_media_audit_log_created_at"), table_name="audit_log", schema="media")
    op.drop_index(op.f("ix_media_audit_log_correlation_id"), table_name="audit_log", schema="media")
    op.drop_index(op.f("ix_media_audit_log_action"), table_name="audit_log", schema="media")
    op.drop_table("audit_log", schema="media")
