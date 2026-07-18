"""projects and project members

Revision ID: 002
Revises: 001
Create Date: 2026-05-24
"""
from alembic import op
import sqlalchemy as sa

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "request_projects",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("color", sa.String(length=20), nullable=False, server_default="#3b82f6"),
        sa.Column("budget_limit", sa.Numeric(18, 2), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="KZT"),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("request_users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("department_id", sa.Integer(), sa.ForeignKey("request_departments.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("name", name="uq_request_projects_name"),
    )
    op.create_index("ix_request_projects_owner_id", "request_projects", ["owner_id"])
    op.create_index("ix_request_projects_department_id", "request_projects", ["department_id"])
    op.create_index("ix_request_projects_created_at", "request_projects", ["created_at"])

    op.create_table(
        "request_project_members",
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("request_projects.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("request_users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("role", sa.String(length=20), nullable=False, server_default="member"),
        sa.Column("granted_by", sa.Integer(), nullable=True),
        sa.Column("granted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("request_project_members")
    op.drop_index("ix_request_projects_created_at", table_name="request_projects")
    op.drop_index("ix_request_projects_department_id", table_name="request_projects")
    op.drop_index("ix_request_projects_owner_id", table_name="request_projects")
    op.drop_table("request_projects")
