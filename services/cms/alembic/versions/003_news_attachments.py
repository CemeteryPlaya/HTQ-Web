"""Add cms.news_attachments table.

Revision ID: 0003_news_attachments
Revises: 0002_cms_audit_schema
Create Date: 2026-05-06 00:00:00.000000

Stores binary assets (cover images + post attachments) attached to a news
post. Files themselves live in the ``htqweb-cms`` S3 bucket under
``news/<id>/attachments/...`` and ``news/<id>/cover.<ext>``; this table
holds the metadata so the API can list / delete them without scanning S3.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0003_news_attachments"
down_revision: Union[str, None] = "0002_cms_audit_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "news_attachments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "news_id",
            sa.Integer(),
            sa.ForeignKey("cms.news.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "role",
            sa.String(length=20),
            nullable=False,
            server_default="attachment",
        ),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("content_type", sa.String(length=255), nullable=False),
        sa.Column("storage_path", sa.String(length=1024), nullable=False),
        sa.Column("uploaded_by", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        schema="cms",
    )
    op.create_index(
        op.f("ix_cms_news_attachments_news_id"),
        "news_attachments",
        ["news_id"],
        schema="cms",
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_cms_news_attachments_news_id"),
        table_name="news_attachments",
        schema="cms",
    )
    op.drop_table("news_attachments", schema="cms")
