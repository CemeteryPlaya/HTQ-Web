"""Курс «не позже даты» — сравнение тендера на дату вскрытия (T-12, тендер T5.4).

``exchange_rate`` ищет строго на дату и в выходной вернёт ``None``; сравнению
нужен последний опубликованный курс не позже даты вскрытия."""

from datetime import date
from decimal import Decimal

import pytest

from apps.refdata import interface
from apps.refdata.models import ExchangeRate

pytestmark = pytest.mark.django_db


def _rate(on: date, value: str, currency: str = "USD") -> None:
    ExchangeRate.objects.create(currency_code=currency, on_date=on, rate=Decimal(value),
                                source="nbrk")


def test_weekend_takes_friday():
    _rate(date(2026, 10, 15), "514.80")      # четверг
    _rate(date(2026, 10, 16), "515.20")      # пятница
    got = interface.exchange_rate_on_or_before("USD", date(2026, 10, 18))   # воскресенье
    assert got == interface.RateOut(rate=Decimal("515.200000"), on_date=date(2026, 10, 16))


def test_exact_date_wins():
    _rate(date(2026, 10, 16), "514.80")
    _rate(date(2026, 10, 17), "515.20")
    assert interface.exchange_rate_on_or_before("USD", date(2026, 10, 16)).on_date == date(2026, 10, 16)


def test_no_rate_at_all_is_none():
    _rate(date(2026, 10, 20), "516.00")      # только позже даты
    assert interface.exchange_rate_on_or_before("USD", date(2026, 10, 19)) is None
    assert interface.exchange_rate_on_or_before("CNY", date(2026, 10, 19)) is None


def test_kzt_is_one_on_the_date():
    assert interface.exchange_rate_on_or_before("KZT", date(2026, 10, 19)) == interface.RateOut(
        rate=Decimal("1"), on_date=date(2026, 10, 19))
