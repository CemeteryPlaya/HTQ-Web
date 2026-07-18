"""Production calendar helpers for Kazakhstan."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable

from app.models.sequence import ProductionDay


DayType = str

# Source: official Kazakhstan 2026 holiday calendar published on gov.kz:
# https://www.gov.kz/article/33969?lang=ru
# https://www.gov.kz/article/16887?lang=en
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


def base_day_type(day: date) -> DayType:
    if day in KZ_HOLIDAYS_2026:
        return "holiday"
    if day.weekday() >= 5:
        return "weekend"
    return "working"


def base_note(day: date) -> str | None:
    return KZ_HOLIDAYS_2026.get(day)


def iter_calendar_days(
    start: date,
    end: date,
    overrides: dict[date, ProductionDay] | None = None,
) -> Iterable[dict[str, object]]:
    """Generate calendar rows with a stable year-local working day counter."""
    overrides = overrides or {}
    current = date(start.year, 1, 1)
    working_days = 0

    while current <= end:
        stored = overrides.get(current)
        day_type = stored.day_type if stored else base_day_type(current)
        note = base_note(current) or (stored.note if stored else None)

        if day_type in {"working", "short"}:
            working_days += 1

        if current >= start:
            yield {
                "date": current,
                "day_type": day_type,
                "note": note,
                "working_days_since_epoch": working_days,
            }

        current += timedelta(days=1)


def build_2026_seed_rows() -> list[dict[str, object]]:
    return list(iter_calendar_days(date(2026, 1, 1), date(2026, 12, 31)))
