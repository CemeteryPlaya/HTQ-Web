"""«Золотые даты» рабочих дней (A7.1, Review Focus 1).

Литералы посчитаны на коде ДО переезда календаря в ``refdata``; после
переезда тест проходит без правки литералов: рабочие дни задач не сдвинулись.
Переопределения дней кладутся в ту таблицу, которую читает расчёт
(``_put_override``), — смена хранилища тест не меняет.
"""

from __future__ import annotations

import datetime as dt

import pytest

from apps.tasks.services import calendar_service, plan_fact_service, sequence_service

D = dt.date


def _put_override(day: dt.date, day_type: str) -> None:
    try:
        from apps.refdata.models import ProductionDay
    except ImportError:  # до переезда
        from apps.tasks.models import ProductionDay
    ProductionDay.objects.create(date=day, day_type=day_type, working_days_since_epoch=0)


RANGES = {
    "plain_week": (D(2026, 6, 8), D(2026, 6, 14)),
    "weekend_only": (D(2026, 6, 13), D(2026, 6, 14)),
    "nauryz_transfer": (D(2026, 3, 16), D(2026, 3, 27)),
    "year_boundary": (D(2026, 12, 28), D(2027, 1, 8)),
    "reversed": (D(2026, 6, 10), D(2026, 6, 1)),
}
GOLDEN_BASE = {"plain_week": 5, "weekend_only": 0, "nauryz_transfer": 7,
               "year_boundary": 7, "reversed": None}
GOLDEN_MEASURE = (7, 12)
GOLDEN_DUE = [D(2026, 3, 18), D(2026, 3, 20), D(2026, 3, 27), D(2026, 4, 1)]
GOLDEN_PLAN = (0.7142857142857143, 0.75)
GOLDEN_HOLIDAY = (8, [D(2026, 3, 20), D(2026, 3, 23), D(2026, 3, 26)])
GOLDEN_OVR = (10, [D(2026, 6, 5), D(2026, 6, 6), D(2026, 6, 9), D(2026, 6, 12)], 0.8)


@pytest.mark.django_db
def test_golden_base_calendar():
    got = {k: calendar_service.working_days_between(*v) for k, v in RANGES.items()}
    assert got == GOLDEN_BASE


@pytest.mark.django_db
def test_golden_measures_and_due_dates():
    start, end = D(2026, 3, 16), D(2026, 3, 27)
    assert calendar_service.days_between(start, end, working=True) == GOLDEN_MEASURE[0]
    assert calendar_service.days_between(start, end, working=False) == GOLDEN_MEASURE[1]
    due = [sequence_service.due_date_from_working_days(D(2026, 3, 18), n) for n in (1, 3, 5, 8)]
    assert due == GOLDEN_DUE
    assert sequence_service.due_date_from_working_days(D(2026, 12, 28), 5) == D(2027, 1, 5)
    assert plan_fact_service.plan_percent(start, end, D(2026, 3, 24), working=True) == GOLDEN_PLAN[0]
    assert plan_fact_service.plan_percent(start, end, D(2026, 3, 24), working=False) == GOLDEN_PLAN[1]


@pytest.mark.django_db
def test_golden_manual_overrides():
    _put_override(D(2026, 6, 6), "working")   # рабочая суббота
    _put_override(D(2026, 6, 10), "holiday")  # ручной праздник в среду
    _put_override(D(2026, 6, 11), "short")    # сокращённый день — рабочий
    assert calendar_service.working_days_between(D(2026, 6, 1), D(2026, 6, 14)) == GOLDEN_OVR[0]
    due = [sequence_service.due_date_from_working_days(D(2026, 6, 5), n) for n in (1, 2, 4, 6)]
    assert due == GOLDEN_OVR[1]
    assert plan_fact_service.plan_percent(D(2026, 6, 1), D(2026, 6, 12), D(2026, 6, 9),
                                          working=True) == GOLDEN_OVR[2]


@pytest.mark.django_db
def test_golden_override_turns_a_state_holiday_into_a_working_day():
    """Ручное «рабочий» поверх госпраздника (Наурыз 23.03.2026 — перенос).

    Литералы посчитаны на СТАРОМ коде (копия HEAD без правок A7.1, tasks.ProductionDay,
    ``TEST_DB_NAME=htqweb_red71``) тем же набором вызовов, что ниже."""
    _put_override(D(2026, 3, 23), "working")
    assert calendar_service.working_days_between(D(2026, 3, 16), D(2026, 3, 27)) == GOLDEN_HOLIDAY[0]
    due = [sequence_service.due_date_from_working_days(D(2026, 3, 20), n) for n in (1, 2, 3)]
    assert due == GOLDEN_HOLIDAY[1]
