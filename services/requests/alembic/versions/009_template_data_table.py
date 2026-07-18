"""template data table links (reference_source.template_id, reference_row.instance_id)

Revision ID: 009
Revises: 008
Create Date: 2026-07-16
"""
from alembic import op
import sqlalchemy as sa

revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("request_reference_sources", sa.Column("template_id", sa.Integer(), nullable=True))
    op.create_index("ix_request_reference_sources_template_id", "request_reference_sources", ["template_id"])
    op.add_column("request_reference_rows", sa.Column("instance_id", sa.Integer(), nullable=True))
    op.create_index("ix_request_reference_rows_instance_id", "request_reference_rows", ["instance_id"])


def downgrade() -> None:
    op.drop_index("ix_request_reference_rows_instance_id", table_name="request_reference_rows")
    op.drop_column("request_reference_rows", "instance_id")
    op.drop_index("ix_request_reference_sources_template_id", table_name="request_reference_sources")
    op.drop_column("request_reference_sources", "template_id")
