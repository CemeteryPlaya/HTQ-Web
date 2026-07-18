"""form templates + versions

Revision ID: 003
Revises: 002
Create Date: 2026-05-24
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "request_form_templates",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("request_projects.id", ondelete="SET NULL"), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("slug", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("icon", sa.String(length=50), nullable=False, server_default=""),
        sa.Column("color", sa.String(length=20), nullable=False, server_default="#3b82f6"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("current_version_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("project_id", "slug", name="uq_request_form_templates_project_slug"),
    )
    op.create_index("ix_request_form_templates_project_id", "request_form_templates", ["project_id"])
    op.create_index("ix_request_form_templates_created_at", "request_form_templates", ["created_at"])

    op.create_table(
        "request_form_template_versions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("template_id", sa.Integer(), sa.ForeignKey("request_form_templates.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("schema_json", JSONB(), nullable=False),
        sa.Column("workflow_json", JSONB(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("published_by", sa.Integer(), nullable=True),
        sa.UniqueConstraint("template_id", "version", name="uq_request_form_template_versions_tv"),
    )
    op.create_index("ix_request_form_template_versions_template_id", "request_form_template_versions", ["template_id"])


def downgrade() -> None:
    op.drop_index("ix_request_form_template_versions_template_id", table_name="request_form_template_versions")
    op.drop_table("request_form_template_versions")
    op.drop_index("ix_request_form_templates_created_at", table_name="request_form_templates")
    op.drop_index("ix_request_form_templates_project_id", table_name="request_form_templates")
    op.drop_table("request_form_templates")
