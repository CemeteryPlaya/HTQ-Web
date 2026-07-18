"""Rework calendar_events for first-class datetime support.

Why
---
Until now ``calendar_events`` only stored ``start_date`` / ``end_date``
(both ``Date``). The timeline endpoint synthesised ``T00:00:00`` /
``T23:59:59`` so every event was effectively all-day, and the UI's
``time`` / ``time_end`` inputs were silently discarded.

This migration:

1. Adds ``start_at`` / ``end_at`` (``timestamptz``), ``is_all_day`` and
   ``event_type`` columns and ``conference_room_id`` for video meetings.
2. Backfills the new columns from the old ones so existing rows still
   render correctly.
3. Drops the legacy ``start_date`` / ``end_date`` columns — the timeline
   endpoint reads ``start_at`` / ``end_at`` from now on.

Revision ID: 007
Revises: 006
Create Date: 2026-05-12
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- 1. New columns (nullable / defaulted so the backfill is safe) -----
    op.add_column(
        "calendar_events",
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "calendar_events",
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "calendar_events",
        sa.Column(
            "is_all_day",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.add_column(
        "calendar_events",
        sa.Column(
            "event_type",
            sa.String(length=20),
            nullable=False,
            server_default="personal",
        ),
    )
    op.add_column(
        "calendar_events",
        sa.Column("conference_room_id", sa.String(length=64), nullable=True),
    )

    # --- 2. Backfill ------------------------------------------------------
    # All-day legacy rows: start_at = start_date 00:00, end_at = end_date 23:59:59.
    op.execute(
        """
        UPDATE calendar_events
        SET start_at = start_date::timestamptz,
            end_at = (end_date::timestamptz + interval '1 day' - interval '1 second'),
            is_all_day = true
        WHERE start_at IS NULL
        """
    )
    # Derive event_type from existing flags so the new column stays a single
    # source of truth going forward.
    op.execute(
        """
        UPDATE calendar_events
        SET event_type = CASE
            WHEN is_global THEN 'common'
            WHEN department_id IS NOT NULL THEN 'department'
            ELSE 'personal'
        END
        """
    )

    # --- 3. Tighten constraints + drop legacy columns ---------------------
    op.alter_column("calendar_events", "start_at", nullable=False)
    op.alter_column("calendar_events", "end_at", nullable=False)
    op.alter_column("calendar_events", "is_all_day", server_default=None)
    op.alter_column("calendar_events", "event_type", server_default=None)

    op.create_check_constraint(
        "ck_calendar_event_type",
        "calendar_events",
        "event_type IN ('personal','department','common','conference')",
    )
    op.create_check_constraint(
        "ck_calendar_event_range",
        "calendar_events",
        "end_at >= start_at",
    )

    op.create_index(
        "ix_calendar_events_start_at", "calendar_events", ["start_at"]
    )
    op.create_index(
        "ix_calendar_events_end_at", "calendar_events", ["end_at"]
    )
    op.create_index(
        "ix_calendar_events_event_type", "calendar_events", ["event_type"]
    )

    # Drop the old date-only columns + their indexes.
    op.drop_index(
        "ix_calendar_events_start_date", table_name="calendar_events"
    )
    op.drop_index("ix_calendar_events_end_date", table_name="calendar_events")
    op.drop_column("calendar_events", "start_date")
    op.drop_column("calendar_events", "end_date")


def downgrade() -> None:
    # Restore legacy date columns from start_at/end_at.
    op.add_column(
        "calendar_events", sa.Column("start_date", sa.Date(), nullable=True)
    )
    op.add_column(
        "calendar_events", sa.Column("end_date", sa.Date(), nullable=True)
    )
    op.execute(
        """
        UPDATE calendar_events
        SET start_date = start_at::date,
            end_date = end_at::date
        """
    )
    op.alter_column("calendar_events", "start_date", nullable=False)
    op.alter_column("calendar_events", "end_date", nullable=False)
    op.create_index(
        "ix_calendar_events_start_date", "calendar_events", ["start_date"]
    )
    op.create_index(
        "ix_calendar_events_end_date", "calendar_events", ["end_date"]
    )

    op.drop_index(
        "ix_calendar_events_event_type", table_name="calendar_events"
    )
    op.drop_index("ix_calendar_events_end_at", table_name="calendar_events")
    op.drop_index(
        "ix_calendar_events_start_at", table_name="calendar_events"
    )
    op.drop_constraint(
        "ck_calendar_event_range", "calendar_events", type_="check"
    )
    op.drop_constraint(
        "ck_calendar_event_type", "calendar_events", type_="check"
    )
    op.drop_column("calendar_events", "conference_room_id")
    op.drop_column("calendar_events", "event_type")
    op.drop_column("calendar_events", "is_all_day")
    op.drop_column("calendar_events", "end_at")
    op.drop_column("calendar_events", "start_at")
