"""Kazakhstan production calendar.

Ported verbatim from ``services/task/app/services/production_calendar.py``.
The holiday table and the day-classification rules are business data, not
implementation detail — they decide real deadlines, so they are copied
value-for-value rather than "cleaned up".

``working_days_since_epoch`` is the running count of working days from
1 January of the row's own year. The name says "epoch" but the counter
resets each year — that is the original's behaviour (``iter_calendar_days``
starts at ``date(start.year, 1, 1)`` with ``working_days = 0``), and the
deadline lookup only ever compares two rows within one year's window, so the
per-year reset is harmless. Preserved as-is because changing it would
silently shift every stored counter without changing any test.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Iterator

# Source: official Kazakhstan 2026 holiday calendar published on gov.kz —
# https://www.gov.kz/article/33969?lang=ru / https://www.gov.kz/article/16887
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

# Day types that count toward the working-day total. "short" is a
# pre-holiday shortened day — still a working day for deadline purposes.
WORKING_DAY_TYPES = frozenset({"working", "short"})


def base_day_type(day: date) -> str:
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
    overrides: dict[date, object] | None = None,
) -> Iterator[dict]:
    """Yield calendar rows for ``start..end`` with the running counter.

    ``overrides`` maps a date to a stored ``ProductionDay`` whose
    ``day_type``/``note`` an administrator has edited; it takes precedence
    over the computed classification. Note the asymmetry, kept from the
    original: an override can change the *type* of a holiday, but
    ``base_note`` still wins for the *note* — the holiday's name is not
    something a per-day override is meant to rewrite.

    Iteration always begins at 1 January of ``start``'s year even when
    ``start`` is later, because the counter must be correct for the first
    yielded row; rows before ``start`` are counted but not emitted.
    """
    overrides = overrides or {}
    current = date(start.year, 1, 1)
    working_days = 0

    while current <= end:
        stored = overrides.get(current)
        day_type = stored.day_type if stored else base_day_type(current)
        note = base_note(current) or (stored.note if stored else None)

        if day_type in WORKING_DAY_TYPES:
            working_days += 1

        if current >= start:
            yield {
                "date": current,
                "day_type": day_type,
                "note": note,
                "working_days_since_epoch": working_days,
            }

        current += timedelta(days=1)


def build_year_rows(year: int, overrides: dict[date, object] | None = None) -> list[dict]:
    """All calendar rows for ``year`` (the original's ``build_2026_seed_rows``
    generalised to any year — 2026 is the only year with holiday data, so
    other years come out as plain weekday/weekend)."""
    return list(iter_calendar_days(date(year, 1, 1), date(year, 12, 31), overrides))
