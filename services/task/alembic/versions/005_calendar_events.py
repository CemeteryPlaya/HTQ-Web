"""Create calendar_events and event_exceptions tables.

Revision ID: 005_calendar_events
Revises: 004_merge_heads
Create Date: 2026-05-06

The CalendarEvent / EventException ORM models were added to
``app.models.calendar`` and wired into the timeline endpoint
(``GET /api/tasks/v1/calendar/timeline/``) without a corresponding
migration, so every page that polls the calendar widget gets a 500
``UndefinedTableError: relation "calendar_events" does not exist``.

This migration creates both tables exactly as declared by the models.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "005_calendar_events"
down_revision: Union[str, None] = "004_merge_heads"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "calendar_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("color", sa.String(length=20), nullable=True),
        sa.Column(
            "is_global",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("department_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_calendar_events_start_date", "calendar_events", ["start_date"]
    )
    op.create_index("ix_calendar_events_end_date", "calendar_events", ["end_date"])
    op.create_index(
        "ix_calendar_events_department_id", "calendar_events", ["department_id"]
    )

    op.create_table(
        "event_exceptions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.Integer(), nullable=False),
        sa.Column("exception_date", sa.Date(), nullable=False),
        sa.Column(
            "is_cancelled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["event_id"], ["calendar_events.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_event_exceptions_event_id", "event_exceptions", ["event_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_event_exceptions_event_id", table_name="event_exceptions")
    op.drop_table("event_exceptions")

    op.drop_index(
        "ix_calendar_events_department_id", table_name="calendar_events"
    )
    op.drop_index("ix_calendar_events_end_date", table_name="calendar_events")
    op.drop_index(
        "ix_calendar_events_start_date", table_name="calendar_events"
    )
    op.drop_table("calendar_events")
