"""reference data sources + rows

Revision ID: 008
Revises: 007
Create Date: 2026-07-15
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None

_JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "request_reference_sources",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("columns_json", _JSON, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_request_reference_sources_slug", "request_reference_sources", ["slug"], unique=True)

    op.create_table(
        "request_reference_rows",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("request_reference_sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("data_json", _JSON, nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.create_index("ix_request_reference_rows_source_id", "request_reference_rows", ["source_id"])


def downgrade() -> None:
    op.drop_index("ix_request_reference_rows_source_id", table_name="request_reference_rows")
    op.drop_table("request_reference_rows")
    op.drop_index("ix_request_reference_sources_slug", table_name="request_reference_sources")
    op.drop_table("request_reference_sources")
