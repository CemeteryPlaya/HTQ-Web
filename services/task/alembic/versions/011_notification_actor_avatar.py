"""Snapshot the actor's avatar URL on each Notification row.

The notification UI renders the sender's photo in the toast / dropdown.
Until now that URL came from ``task_users.avatar_url`` (a replica fed by
Redis pub/sub). When the replica is empty — fresh dev install, slow
sync, transient Redis outage — the UI falls back to initials.

Storing the URL alongside the notification at write time makes the
display stable: even if the replica is empty the toast still shows the
real avatar that was current when the event fired.

Revision ID: 011
Revises: 010
Create Date: 2026-05-14
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "011"
down_revision: Union[str, None] = "010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        'ALTER TABLE notifications '
        'ADD COLUMN IF NOT EXISTS actor_avatar_url VARCHAR(1024)'
    )


def downgrade() -> None:
    op.execute('ALTER TABLE notifications DROP COLUMN IF EXISTS actor_avatar_url')
