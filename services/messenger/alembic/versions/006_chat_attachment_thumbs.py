"""Add thumbnail + intrinsic size columns to chat attachments.

Lets the chat UI render an actual preview for image attachments instead
of fetching the original (often multi-megabyte) file just to display it
at 280×320, and lets us reserve aspect-ratio space so the bubble doesn't
jump when the image finishes loading.

- ``thumbnail_path`` — S3 object key of a ≤ 256×256 WebP thumbnail.
  ``NULL`` for non-image attachments or for legacy rows uploaded before
  this migration.
- ``width`` / ``height`` — intrinsic pixel size of the original image,
  used for ``aspect-ratio`` on the rendered preview.

Revision ID: 006_chat_attachment_thumbs
Revises: 005_create_audit_log
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from app.core.settings import settings


revision = "006_chat_attachment_thumbs"
down_revision = "005_create_audit_log"
branch_labels = None
depends_on = None

SCHEMA = settings.db_schema


def upgrade() -> None:
    # Use raw ``ADD COLUMN IF NOT EXISTS`` so the migration is safe to re-run
    # against schemas that already partially applied it (e.g. a previous run
    # added the first column then crashed on the second).
    op.execute(
        f'ALTER TABLE "{SCHEMA}".chat_attachments '
        'ADD COLUMN IF NOT EXISTS thumbnail_path VARCHAR(2048)'
    )
    op.execute(
        f'ALTER TABLE "{SCHEMA}".chat_attachments '
        'ADD COLUMN IF NOT EXISTS width INTEGER'
    )
    op.execute(
        f'ALTER TABLE "{SCHEMA}".chat_attachments '
        'ADD COLUMN IF NOT EXISTS height INTEGER'
    )


def downgrade() -> None:
    op.execute(
        f'ALTER TABLE "{SCHEMA}".chat_attachments '
        'DROP COLUMN IF EXISTS height'
    )
    op.execute(
        f'ALTER TABLE "{SCHEMA}".chat_attachments '
        'DROP COLUMN IF EXISTS width'
    )
    op.execute(
        f'ALTER TABLE "{SCHEMA}".chat_attachments '
        'DROP COLUMN IF EXISTS thumbnail_path'
    )
