"""Add avatar_url to task_users replica.

The user-service ``user.upserted`` payload already carries ``avatar_url``;
we just didn't mirror it locally. The notifications API joins on this
column so the rich messenger toast can render the sender's photo without
a cross-service round-trip.

Revision ID: 010
Revises: 009
Create Date: 2026-05-14
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "010"
down_revision: Union[str, None] = "009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        'ALTER TABLE task_users ADD COLUMN IF NOT EXISTS avatar_url VARCHAR(1024)'
    )


def downgrade() -> None:
    op.execute('ALTER TABLE task_users DROP COLUMN IF EXISTS avatar_url')
