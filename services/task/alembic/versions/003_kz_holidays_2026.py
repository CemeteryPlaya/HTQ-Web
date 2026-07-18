"""Add Kazakhstan 2026 production calendar notes and seed days.

Revision ID: 003_kz_holidays_2026
Revises: 002_replica_tables
Create Date: 2026-05-06
"""

from datetime import date, timedelta
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "003_kz_holidays_2026"
down_revision: Union[str, None] = "002_replica_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Source: official Kazakhstan 2026 holiday calendar published on gov.kz.
KZ_HOLIDAYS_2026: dict[date, str] = {
    date(2026, 1, 1): "Новый год",
    date(2026, 1, 2): "Новый год",
    date(2026, 1, 7): "Православное Рождество",
    date(2026, 3, 8): "Международный женский день",
    date(2026, 3, 9): "Международный женский день (перенос)",
    date(2026, 3, 21): "Наурыз мейрамы",
    date(2026, 3, 22): "Наурыз мейрамы",
    date(2026, 3, 23): "Наурыз мейрамы",
    date(2026, 3, 24): "Наурыз мейрамы (перенос)",
    date(2026, 3, 25): "Наурыз мейрамы (перенос)",
    date(2026, 5, 1): "Праздник единства народа Казахстана",
    date(2026, 5, 7): "День защитника Отечества",
    date(2026, 5, 9): "День Победы",
    date(2026, 5, 11): "День Победы (перенос)",
    date(2026, 5, 27): "Курбан-айт",
    date(2026, 7, 6): "День Столицы",
    date(2026, 8, 30): "День Конституции Республики Казахстан",
    date(2026, 8, 31): "День Конституции Республики Казахстан (перенос)",
    date(2026, 10, 25): "День Республики",
    date(2026, 10, 26): "День Республики (перенос)",
    date(2026, 12, 16): "День Независимости",
}


def _build_2026_seed_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    current = date(2026, 1, 1)
    end = date(2026, 12, 31)
    working_days = 0

    while current <= end:
        if current in KZ_HOLIDAYS_2026:
            day_type = "holiday"
        elif current.weekday() >= 5:
            day_type = "weekend"
        else:
            day_type = "working"

        if day_type == "working":
            working_days += 1

        rows.append(
            {
                "date": current,
                "day_type": day_type,
                "note": KZ_HOLIDAYS_2026.get(current),
                "working_days_since_epoch": working_days,
            }
        )
        current += timedelta(days=1)

    return rows


def upgrade() -> None:
    op.add_column("production_days", sa.Column("note", sa.String(length=255), nullable=True))

    statement = sa.text(
        """
        INSERT INTO production_days (date, day_type, note, working_days_since_epoch)
        VALUES (:date, :day_type, :note, :working_days_since_epoch)
        ON CONFLICT (date) DO UPDATE SET
            day_type = EXCLUDED.day_type,
            note = EXCLUDED.note,
            working_days_since_epoch = EXCLUDED.working_days_since_epoch,
            updated_at = now()
        """
    )
    op.get_bind().execute(statement, _build_2026_seed_rows())


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            DELETE FROM production_days
            WHERE date >= DATE '2026-01-01'
              AND date <= DATE '2026-12-31'
            """
        )
    )
    op.drop_column("production_days", "note")
