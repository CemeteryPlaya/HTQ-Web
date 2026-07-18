"""init schema and replica tables

Revision ID: 001
Revises:
Create Date: 2026-05-24
"""
from alembic import op
import sqlalchemy as sa

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "request_departments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("name", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("parent_id", sa.Integer(), nullable=True),
        sa.Column("head_user_id", sa.Integer(), nullable=True),
    )
    op.create_index("ix_request_departments_parent_id", "request_departments", ["parent_id"])
    op.create_index("ix_request_departments_head_user_id", "request_departments", ["head_user_id"])

    op.create_table(
        "request_users",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("username", sa.String(length=150), nullable=False, server_default=""),
        sa.Column("email", sa.String(length=254), nullable=False, server_default=""),
        sa.Column("first_name", sa.String(length=150), nullable=False, server_default=""),
        sa.Column("last_name", sa.String(length=150), nullable=False, server_default=""),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_elevated", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("request_users")
    op.drop_index("ix_request_departments_head_user_id", table_name="request_departments")
    op.drop_index("ix_request_departments_parent_id", table_name="request_departments")
    op.drop_table("request_departments")
