"""Add avatar_url column to chat rooms.

The ``RoomRead`` schema and the SPA already expose ``avatar_url`` for the
room object — but until now there was no column to back it. Group chats
fell back to a generic Users icon, even though the UI was ready to
render a real picture. This adds the storage column. A follow-up patch
wires up the create / edit endpoints.

Revision ID: 007_room_avatar
Revises: 006_chat_attachment_thumbs
"""

from __future__ import annotations

from alembic import op

from app.core.settings import settings


revision = "007_room_avatar"
down_revision = "006_chat_attachment_thumbs"
branch_labels = None
depends_on = None

SCHEMA = settings.db_schema


def upgrade() -> None:
    op.execute(
        f'ALTER TABLE "{SCHEMA}".rooms '
        'ADD COLUMN IF NOT EXISTS avatar_url VARCHAR(1024)'
    )


def downgrade() -> None:
    op.execute(
        f'ALTER TABLE "{SCHEMA}".rooms '
        'DROP COLUMN IF EXISTS avatar_url'
    )
