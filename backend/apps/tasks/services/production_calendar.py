"""Kazakhstan production calendar.

Ported from ``services/task/app/services/production_calendar.py``. The
day-classification rules are business data, not implementation detail — they
decide real deadlines, so they are kept value-for-value rather than "cleaned
up".

The holiday table itself no longer lives here: it moved to
``apps.core.kz_holidays``, shared with ``apps.hr``, and is computed per year
instead of being a hardcoded 2026 dictionary. The output for 2026 is
unchanged — that is pinned by ``apps/core/tests/test_kz_holidays.py``.

``working_days_since_epoch`` is the running count of working days from
1 January of the row's own year. The name says "epoch" but the counter
resets each year — that is the original's behaviour (``iter_calendar_days``
starts at ``date(start.year, 1, 1)`` with ``working_days = 0``). It stays
part of the API response, but nothing computes deadlines from it anymore:
``sequence_service.due_date_from_working_days`` walks the days instead,
precisely so a span crossing 1 January isn't broken by the reset. Preserved
as-is because changing it would silently shift every stored counter.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Iterator

from apps.core import kz_holidays

# Day types that count toward the working-day total. "short" is a
# pre-holiday shortened day — still a working day for deadline purposes.
WORKING_DAY_TYPES = frozenset({"working", "short"})


def base_day_type(day: date) -> str:
    if kz_holidays.is_holiday(day):
        return "holiday"
    if day.weekday() >= 5:
        return "weekend"
    return "working"


def base_note(day: date) -> str | None:
    return kz_holidays.holiday_note(day)


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
    generalised to any year — holidays now come from ``apps.core.kz_holidays``,
    which computes them for every year, so no year comes out bare)."""
    return list(iter_calendar_days(date(year, 1, 1), date(year, 12, 31), overrides))
