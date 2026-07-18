"""Mark system bot replicas in chat_user_replicas.

System bots (Календарь / Задачи / Почта / Файлы / Новости) live in the
same table as real users — that way bot DMs reuse the existing room +
message + Socket.IO pipeline without a parallel data model.

The bot rows are inserted on application startup by
``app.services.system_bots.ensure_system_bots`` with IDs in the
``9_000_001..9_000_005`` range (way above realistic user_id) so no
collision with user-service IDs is possible.

Revision ID: 008_chat_user_is_bot
Revises: 007_room_avatar
"""

from __future__ import annotations

from alembic import op

from app.core.settings import settings


revision = "008_chat_user_is_bot"
down_revision = "007_room_avatar"
branch_labels = None
depends_on = None

SCHEMA = settings.db_schema


def upgrade() -> None:
    op.execute(
        f'ALTER TABLE "{SCHEMA}".chat_user_replicas '
        'ADD COLUMN IF NOT EXISTS is_bot BOOLEAN NOT NULL DEFAULT FALSE'
    )
    op.execute(
        f'CREATE INDEX IF NOT EXISTS ix_chat_user_replicas_is_bot '
        f'ON "{SCHEMA}".chat_user_replicas (is_bot) WHERE is_bot = TRUE'
    )


def downgrade() -> None:
    op.execute(
        f'DROP INDEX IF EXISTS "{SCHEMA}".ix_chat_user_replicas_is_bot'
    )
    op.execute(
        f'ALTER TABLE "{SCHEMA}".chat_user_replicas DROP COLUMN IF EXISTS is_bot'
    )
