"""Add RSVP status to calendar event participants.

Lets an invitee respond "Иду" / "Не иду" without the author seeing them
silently disappear from the participants list. The status defaults to
``pending`` for new invites; the author is upserted to ``accepted`` on
create / update by the API layer.

Revision ID: 008
Revises: 007
Create Date: 2026-05-12
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "calendar_event_participants",
        sa.Column(
            "rsvp_status",
            sa.String(length=16),
            nullable=False,
            server_default="pending",
        ),
    )
    op.create_check_constraint(
        "ck_calendar_event_participant_status",
        "calendar_event_participants",
        "rsvp_status IN ('pending','accepted','declined')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_calendar_event_participant_status",
        "calendar_event_participants",
        type_="check",
    )
    op.drop_column("calendar_event_participants", "rsvp_status")
