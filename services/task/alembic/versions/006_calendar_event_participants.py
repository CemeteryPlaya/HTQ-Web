"""Allow a calendar event to invite specific users (M:M participants).

Adds two things to the calendar layer:

1. ``calendar_events.creator_id`` — who created the event. Until now the
   timeline endpoint hard-coded ``creator: 0`` which was fine when every
   event was either company-wide (``is_global``) or department-scoped,
   but for "общее совещание"-style invites we need to know the author so
   the event always stays visible on their own calendar.
2. ``calendar_event_participants`` — a thin (event_id, user_id) join
   table. Visibility from the API side is then: caller sees the event if
   ``is_global`` OR ``creator_id == me`` OR ``me`` appears in the
   participants table.

No FK to a user table — task-service syncs a ``task_users`` replica, but
not every invited user is guaranteed to have a row there (cross-service
event ordering). Soft reference by integer id is enough.

Revision ID: 006
Revises: 005_calendar_events
Create Date: 2026-05-12
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "006"
down_revision: Union[str, None] = "005_calendar_events"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "calendar_events",
        sa.Column("creator_id", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_calendar_events_creator_id",
        "calendar_events",
        ["creator_id"],
    )

    op.create_table(
        "calendar_event_participants",
        sa.Column("event_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("event_id", "user_id"),
        sa.ForeignKeyConstraint(
            ["event_id"], ["calendar_events.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_calendar_event_participants_user_id",
        "calendar_event_participants",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_calendar_event_participants_user_id",
        table_name="calendar_event_participants",
    )
    op.drop_table("calendar_event_participants")

    op.drop_index(
        "ix_calendar_events_creator_id", table_name="calendar_events"
    )
    op.drop_column("calendar_events", "creator_id")
