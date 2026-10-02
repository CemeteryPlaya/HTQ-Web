"""Производственный календарь РК — один на группу (A7.1, D-S7-1).

Перенесён из ``apps.tasks.services.production_calendar`` и расчётов
``calendar_service`` целиком: правила классификации дней — бизнес-данные,
они решают реальные сроки. Историческая справка оригинала:

The
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

from django.db import transaction

from apps.core import kz_holidays

from ..models import ProductionDay

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


# ── расчёты по хранимым переопределениям ────────────────────────────────

def _overrides(start: date, end: date) -> dict[date, ProductionDay]:
    return {day.date: day for day in
            ProductionDay.objects.filter(date__gte=start, date__lte=end)}


def list_production_days(start: date, end: date) -> list[dict]:
    """Базовый календарь РК с хранимыми строками как ручными переопределениями.

    Переопределения берутся с 1 января, чтобы счётчик рабочих дней первой
    запрошенной даты был верным.
    """
    return list(iter_calendar_days(start, end, _overrides(date(start.year, 1, 1), end)))


@transaction.atomic
def update_production_day(target_date: date, *, day_type: str, note: str | None) -> ProductionDay:
    day = ProductionDay.objects.filter(date=target_date).first()
    if day is None:
        day = ProductionDay(date=target_date, working_days_since_epoch=0)
    day.day_type = day_type
    # Явная заметка важнее; иначе возвращается название праздника.
    day.note = note if note is not None else base_note(target_date)
    day.save()
    _recalculate_year(target_date.year)
    day.refresh_from_db()
    return day


def _recalculate_year(year: int) -> None:
    """Перештамповать ``working_days_since_epoch`` у всех хранимых строк года:
    смена одного дня сдвигает счётчик всех последующих."""
    start, end = date(year, 1, 1), date(year, 12, 31)
    overrides = _overrides(start, end)
    if not overrides:
        return
    updated = []
    for item in iter_calendar_days(start, end, overrides):
        stored = overrides.get(item["date"])
        if stored is not None:
            stored.working_days_since_epoch = int(item["working_days_since_epoch"])
            updated.append(stored)
    ProductionDay.objects.bulk_update(updated, ["working_days_since_epoch"])


def day_type(day: date) -> str:
    stored = ProductionDay.objects.filter(date=day).values_list("day_type", flat=True).first()
    return stored or base_day_type(day)


def is_working_day(day: date) -> bool:
    return day_type(day) in WORKING_DAY_TYPES


def working_days_between(start: date | None, end: date | None) -> int | None:
    """Рабочих дней в ``start..end`` включительно; ``None`` — перевёрнутый или
    неполный отрезок. Считается обходом дней, а не разностью счётчика:
    счётчик сбрасывается 1 января и на отрезке через Новый год дал бы минус."""
    if start is None or end is None or end < start:
        return None
    overrides = _overrides(date(start.year, 1, 1), end)
    return sum(1 for day in iter_calendar_days(start, end, overrides)
               if day["day_type"] in WORKING_DAY_TYPES)


def calendar_days_between(start: date | None, end: date | None) -> int | None:
    if start is None or end is None or end < start:
        return None
    return (end - start).days + 1


def days_between(start: date | None, end: date | None, *, working: bool) -> int | None:
    """Длительность отрезка в мере проекта: рабочие или календарные дни."""
    return (working_days_between(start, end) if working
            else calendar_days_between(start, end))


# Потолок обхода — как у прежней реализации в tasks (sequence_service).
_SCAN_FACTOR = 3
_SCAN_SLACK_DAYS = 30


def add_working_days(start: date, count: int, *, max_count: int = 3650) -> date | None:
    """Дата, отстоящая на ``count`` рабочих дней от ``start`` включительно:
    1 рабочий день от понедельника — понедельник. ``None`` — ``count`` не
    положителен, выше ``max_count`` или рабочих дней не набралось в потолке."""
    if count is None or not 1 <= count <= max_count:
        return None
    limit = start + timedelta(days=count * _SCAN_FACTOR + _SCAN_SLACK_DAYS)
    overrides = dict(ProductionDay.objects.filter(date__gte=start, date__lte=limit)
                     .values_list("date", "day_type"))
    seen = 0
    day = start
    while day <= limit:
        if (overrides.get(day) or base_day_type(day)) in WORKING_DAY_TYPES:
            seen += 1
            if seen == count:
                return day
        day += timedelta(days=1)
    return None


# ── банковские дни (A7.2, D-S7-7) ───────────────────────────────────────

_NON_BANK_OVERRIDES = frozenset({"holiday", "weekend"})


def is_bank_day(day: date) -> bool:
    """Банк работает: Пн–Пт и не праздник РК, КРОМЕ дня переноса праздника,
    выпавшего на субботу (в него банк работает; перенос с воскресенья — нет).
    Рабочая суббота и выходные небанковские; ручное «праздник»/«выходной»
    закрывает день и для банка, а ручное «рабочий» банк не открывает."""
    return _bank_day(day, _stored_types(day, day))


def add_bank_days(start: date, count: int, *, max_count: int = 3650) -> date:
    """Дата через ``count`` банковских дней ПОСЛЕ ``start`` (сам ``start`` не
    считается; ``count <= 0`` — ``start``)."""
    if count <= 0:
        return start
    count = min(count, max_count)
    stored = _stored_types(start, start + timedelta(days=count * _SCAN_FACTOR + _SCAN_SLACK_DAYS))
    day = start
    while count > 0:
        day += timedelta(days=1)
        if _bank_day(day, stored):
            count -= 1
    return day


def bank_days_before(day: date, count: int, *, max_count: int = 3650) -> date:
    """День, отстоящий от ``day`` на ``count`` банковских дней назад (сам ``day``
    не считается). Отметка раньше него ждёт банк дольше ``count`` дней.
    ``count`` ограничен ``max_count`` (иначе обход ушёл бы за ``date.min``)."""
    if count <= 0:
        return day
    count = min(count, max_count)
    stored = _stored_types(day - timedelta(days=count * _SCAN_FACTOR + _SCAN_SLACK_DAYS), day)
    while count > 0:
        day -= timedelta(days=1)
        if _bank_day(day, stored):
            count -= 1
    return day


def _stored_types(start: date, end: date) -> dict[date, str]:
    return dict(ProductionDay.objects.filter(date__gte=start, date__lte=end)
                .values_list("date", "day_type"))


def _bank_day(day: date, stored: dict[date, str]) -> bool:
    if stored.get(day) in _NON_BANK_OVERRIDES:
        return False
    if day.weekday() >= 5:
        return False
    if not kz_holidays.is_holiday(day):
        return True
    source = kz_holidays.transfer_source(day)
    return source is not None and source.weekday() == 5
