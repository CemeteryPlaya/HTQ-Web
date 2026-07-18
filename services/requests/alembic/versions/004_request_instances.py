"""request instances + approval actions + activity + watchers

Revision ID: 004
Revises: 003
Create Date: 2026-05-24
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "request_instances",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("template_id", sa.Integer(), sa.ForeignKey("request_form_templates.id", ondelete="CASCADE"), nullable=False),
        sa.Column("template_version_id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("request_projects.id", ondelete="SET NULL"), nullable=True),
        sa.Column("initiator_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"),
        sa.Column("current_node_id", sa.String(length=64), nullable=True),
        sa.Column("form_values_json", JSONB(), nullable=False),
        sa.Column("total_amount", sa.Numeric(18, 2), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("requires_admin_attention", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("code", name="uq_request_instances_code"),
    )
    op.create_index("ix_request_instances_template_id", "request_instances", ["template_id"])
    op.create_index("ix_request_instances_project_id", "request_instances", ["project_id"])
    op.create_index("ix_request_instances_initiator_id", "request_instances", ["initiator_id"])
    op.create_index("ix_request_instances_status", "request_instances", ["status"])
    op.create_index("ix_request_instances_current_node_id", "request_instances", ["current_node_id"])

    op.create_table(
        "request_approval_actions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("request_id", sa.Integer(), sa.ForeignKey("request_instances.id", ondelete="CASCADE"), nullable=False),
        sa.Column("node_id", sa.String(length=64), nullable=False),
        sa.Column("step_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("approver_id", sa.Integer(), nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("action", sa.String(length=20), nullable=True),
        sa.Column("comment", sa.Text(), nullable=False, server_default=""),
        sa.Column("acted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reminded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reminders_sent", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_request_approval_actions_request_id", "request_approval_actions", ["request_id"])
    op.create_index("ix_request_approval_actions_approver_id", "request_approval_actions", ["approver_id"])
    op.create_index(
        "uq_live_action", "request_approval_actions", ["request_id", "node_id", "approver_id"],
        unique=True, postgresql_where=sa.text("acted_at IS NULL"),
    )

    op.create_table(
        "request_activity",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("request_id", sa.Integer(), sa.ForeignKey("request_instances.id", ondelete="CASCADE"), nullable=False),
        sa.Column("actor_id", sa.Integer(), nullable=True),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("payload", JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_request_activity_request_id", "request_activity", ["request_id"])
    op.create_index("ix_request_activity_created_at", "request_activity", ["created_at"])

    op.create_table(
        "request_watchers",
        sa.Column("request_id", sa.Integer(), sa.ForeignKey("request_instances.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("user_id", sa.Integer(), primary_key=True),
    )


def downgrade() -> None:
    op.drop_table("request_watchers")
    op.drop_index("ix_request_activity_created_at", table_name="request_activity")
    op.drop_index("ix_request_activity_request_id", table_name="request_activity")
    op.drop_table("request_activity")
    op.drop_index("uq_live_action", table_name="request_approval_actions")
    op.drop_index("ix_request_approval_actions_approver_id", table_name="request_approval_actions")
    op.drop_index("ix_request_approval_actions_request_id", table_name="request_approval_actions")
    op.drop_table("request_approval_actions")
    for ix in ["current_node_id", "status", "initiator_id", "project_id", "template_id"]:
        op.drop_index(f"ix_request_instances_{ix}", table_name="request_instances")
    op.drop_table("request_instances")
