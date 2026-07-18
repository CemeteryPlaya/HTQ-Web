"""Notification history: read_at + generic target reference.

Today the ``notifications`` table only stores the *fact* that something
was read (``is_read``), not *when*. The history page needs the latter to
show «прочитано 2026-05-12 14:31».

Adds three columns:
- ``read_at`` (timestamptz, nullable) — populated when the user marks the
  row as read. Server-side default stays NULL so historical rows aren't
  retroactively timestamped.
- ``target_type`` (varchar) — string discriminator for what the
  notification points at: ``task``, ``calendar_event``, ``employee``, …
  ``NULL`` means «no clickable target».
- ``target_id`` (int) — id of the target inside its type's namespace.

The legacy ``task_id`` FK stays — task notifications can either populate
the new ``target_type='task'`` + ``target_id`` pair, or keep using
``task_id`` for backwards compat. The history endpoint reads both.

Revision ID: 009
Revises: 008
Create Date: 2026-05-13
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "009"
down_revision: Union[str, None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "notifications",
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "notifications",
        sa.Column("target_type", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "notifications",
        sa.Column("target_id", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_notifications_target",
        "notifications",
        ["target_type", "target_id"],
    )
    op.create_index(
        "ix_notifications_recipient_created",
        "notifications",
        ["recipient_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_notifications_recipient_created", table_name="notifications"
    )
    op.drop_index("ix_notifications_target", table_name="notifications")
    op.drop_column("notifications", "target_id")
    op.drop_column("notifications", "target_type")
    op.drop_column("notifications", "read_at")
