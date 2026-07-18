"""Extend file_metadata with sha256/kind/scope/dimensions and add file_variants.

Revision ID: 0004_meta_and_variants
Revises: 0003_avatar_visibility
Create Date: 2026-05-05 00:30:00.000000

Schema-only migration. Data backfill (sha256 / dimensions for existing rows
+ enqueueing thumbnail jobs) lives in a separate revision so the deploy can
roll forward without blocking on Pillow processing.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0004_meta_and_variants"
down_revision: Union[str, None] = "0003_avatar_visibility"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "file_metadata",
        sa.Column("sha256", sa.String(length=64), nullable=True),
        schema="media",
    )
    op.add_column(
        "file_metadata",
        sa.Column(
            "kind",
            sa.String(length=16),
            server_default="other",
            nullable=False,
        ),
        schema="media",
    )
    op.add_column(
        "file_metadata",
        sa.Column(
            "scope",
            sa.String(length=32),
            server_default="generic",
            nullable=False,
        ),
        schema="media",
    )
    op.add_column(
        "file_metadata",
        sa.Column("width", sa.Integer(), nullable=True),
        schema="media",
    )
    op.add_column(
        "file_metadata",
        sa.Column("height", sa.Integer(), nullable=True),
        schema="media",
    )
    op.add_column(
        "file_metadata",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        schema="media",
    )

    op.create_index(
        "ix_media_file_metadata_sha256",
        "file_metadata",
        ["sha256"],
        unique=False,
        schema="media",
    )
    op.create_index(
        "ix_media_file_metadata_kind",
        "file_metadata",
        ["kind"],
        unique=False,
        schema="media",
    )
    op.create_index(
        "ix_media_file_metadata_scope",
        "file_metadata",
        ["scope"],
        unique=False,
        schema="media",
    )
    op.create_index(
        "ix_media_file_metadata_deleted_at",
        "file_metadata",
        ["deleted_at"],
        unique=False,
        schema="media",
        postgresql_where=sa.text("deleted_at IS NOT NULL"),
    )

    op.create_table(
        "file_variants",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("file_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("variant", sa.String(length=16), nullable=False),
        sa.Column("path", sa.String(length=1024), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("mime", sa.String(length=255), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["file_id"],
            ["media.file_metadata.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("path", name="uq_file_variants_path"),
        sa.UniqueConstraint("file_id", "variant", name="uq_file_variants_file_variant"),
        schema="media",
    )
    op.create_index(
        "ix_media_file_variants_file_id",
        "file_variants",
        ["file_id"],
        unique=False,
        schema="media",
    )


def downgrade() -> None:
    op.drop_index("ix_media_file_variants_file_id", table_name="file_variants", schema="media")
    op.drop_table("file_variants", schema="media")

    op.drop_index("ix_media_file_metadata_deleted_at", table_name="file_metadata", schema="media")
    op.drop_index("ix_media_file_metadata_scope", table_name="file_metadata", schema="media")
    op.drop_index("ix_media_file_metadata_kind", table_name="file_metadata", schema="media")
    op.drop_index("ix_media_file_metadata_sha256", table_name="file_metadata", schema="media")

    op.drop_column("file_metadata", "deleted_at", schema="media")
    op.drop_column("file_metadata", "height", schema="media")
    op.drop_column("file_metadata", "width", schema="media")
    op.drop_column("file_metadata", "scope", schema="media")
    op.drop_column("file_metadata", "kind", schema="media")
    op.drop_column("file_metadata", "sha256", schema="media")
