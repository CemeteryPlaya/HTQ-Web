"""Provisioned mailboxes (Mailcow-backed).

Revision ID: 004_provisioned_mailboxes
Revises: 003
"""

import sqlalchemy as sa
from alembic import op


revision = "004_provisioned_mailboxes"
down_revision = "003"
branch_labels = None
depends_on = None


SCHEMA = "email"


def upgrade() -> None:
    op.create_table(
        "provisioned_mailboxes",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("local_part", sa.String(length=255), nullable=False),
        sa.Column("domain", sa.String(length=255), nullable=False),
        sa.Column("address", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
        sa.Column("quota_mb", sa.Integer(), nullable=False, server_default="1024"),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("address", name="uq_provisioned_mailboxes_address"),
        sa.UniqueConstraint("user_id", name="uq_provisioned_mailboxes_user_id"),
        schema=SCHEMA,
    )
    op.create_index("ix_provisioned_mailboxes_user_id", "provisioned_mailboxes", ["user_id"], schema=SCHEMA)
    op.create_index("ix_provisioned_mailboxes_address", "provisioned_mailboxes", ["address"], schema=SCHEMA)
    op.create_index("ix_provisioned_mailboxes_status", "provisioned_mailboxes", ["status"], schema=SCHEMA)
    op.create_index("ix_provisioned_mailboxes_created_at", "provisioned_mailboxes", ["created_at"], schema=SCHEMA)


def downgrade() -> None:
    op.drop_index("ix_provisioned_mailboxes_created_at", table_name="provisioned_mailboxes", schema=SCHEMA)
    op.drop_index("ix_provisioned_mailboxes_status", table_name="provisioned_mailboxes", schema=SCHEMA)
    op.drop_index("ix_provisioned_mailboxes_address", table_name="provisioned_mailboxes", schema=SCHEMA)
    op.drop_index("ix_provisioned_mailboxes_user_id", table_name="provisioned_mailboxes", schema=SCHEMA)
    op.drop_table("provisioned_mailboxes", schema=SCHEMA)
