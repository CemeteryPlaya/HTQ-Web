"""Банковские дни (A7.2, D-S7-7): Пн–Пт и не праздник РК, КРОМЕ дня переноса
праздника, выпавшего на субботу — в нём банк работает. Перенос с воскресенья,
выходные, рабочая суббота и ручной «праздник» — небанковские."""
from __future__ import annotations

import datetime as dt

import pytest

from apps.refdata import interface as refdata
from apps.refdata.models import ProductionDay

pytestmark = pytest.mark.django_db
D = dt.date


def test_nauryz_2026_transfer_from_saturday_is_a_bank_day_from_sunday_is_not():
    assert refdata.is_bank_day(D(2026, 3, 24)) is True    # перенос с сб 21.03
    assert refdata.is_bank_day(D(2026, 3, 25)) is False   # перенос с вс 22.03
    assert refdata.is_bank_day(D(2026, 3, 23)) is False   # сам праздник, пн
    assert refdata.is_bank_day(D(2026, 3, 26)) is True


def test_weekends_and_plain_weekdays():
    assert refdata.is_bank_day(D(2026, 3, 21)) is False
    assert refdata.is_bank_day(D(2026, 3, 22)) is False
    assert refdata.is_bank_day(D(2026, 9, 28)) is True    # обычный понедельник
    assert refdata.is_bank_day(D(2026, 9, 26)) is False   # обычная суббота


def test_working_saturday_is_not_a_bank_day():
    ProductionDay.objects.create(date=D(2026, 9, 26), day_type="working",
                                 working_days_since_epoch=0)
    assert refdata.is_working_day(D(2026, 9, 26)) is True
    assert refdata.is_bank_day(D(2026, 9, 26)) is False


def test_manual_holiday_override_is_not_a_bank_day():
    ProductionDay.objects.create(date=D(2026, 9, 29), day_type="holiday",
                                 working_days_since_epoch=0)
    assert refdata.is_bank_day(D(2026, 9, 29)) is False
    # Даже день переноса с субботы, если его вручную сделали праздником.
    ProductionDay.objects.create(date=D(2026, 3, 24), day_type="holiday",
                                 working_days_since_epoch=0)
    assert refdata.is_bank_day(D(2026, 3, 24)) is False


def test_add_bank_days_counts_from_the_next_day():
    # Пт 20.03 + 5: 24 (перенос с сб), 26, 27, 30, 31; 23 и 25 — небанковские.
    assert refdata.add_bank_days(D(2026, 3, 20), 5) == D(2026, 3, 31)
    assert refdata.add_bank_days(D(2026, 9, 25), 1) == D(2026, 9, 28)
    assert refdata.add_bank_days(D(2026, 9, 28), 0) == D(2026, 9, 28)


def test_add_bank_days_respects_manual_holiday():
    ProductionDay.objects.create(date=D(2026, 9, 29), day_type="holiday",
                                 working_days_since_epoch=0)
    assert refdata.add_bank_days(D(2026, 9, 28), 1) == D(2026, 9, 30)


def test_bank_days_before_walks_back_over_non_bank_days():
    # От чт 26.03 назад на 3: 25 нет, 24 (1), 23/22/21 нет, 20 (2), 19 (3).
    assert refdata.bank_days_before(D(2026, 3, 26), 3) == D(2026, 3, 19)
    assert refdata.bank_days_before(D(2026, 9, 28), 1) == D(2026, 9, 25)
    assert refdata.bank_days_before(D(2026, 9, 28), 3) == D(2026, 9, 23)
    assert refdata.bank_days_before(D(2026, 9, 30), 3) == D(2026, 9, 25)


def test_manual_working_on_a_weekday_holiday_does_not_open_the_bank():
    for day in (D(2026, 3, 23), D(2026, 3, 25)):
        ProductionDay.objects.create(date=day, day_type="working", working_days_since_epoch=0)
        assert refdata.is_bank_day(day) is False


def test_bank_days_before_clamps_huge_count():
    assert refdata.bank_days_before(D(2026, 9, 28), 10**9) < D(2026, 9, 28)
