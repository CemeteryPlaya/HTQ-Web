"""Ежедневная загрузка курса НБРК (D-15): ручной курс не перезаписывается,
недоступный API не роняет задачу."""

from datetime import date
from decimal import Decimal

import httpx
import pytest

from apps.refdata.models import ExchangeRate
from apps.refdata.services import nbrk

XML = """<?xml version="1.0" encoding="utf-8"?>
<rates><date>27.09.2026</date>
<item><title>USD</title><description>470.12</description><quant>1</quant></item>
<item><title>RUB</title><description>5.43</description><quant>1</quant></item>
<item><title>KGS</title><description>53.20</description><quant>10</quant></item>
</rates>"""


class _Resp:
    status_code = 200
    text = XML

    def raise_for_status(self):
        return None


@pytest.mark.django_db
def test_rates_are_loaded_per_unit(monkeypatch):
    monkeypatch.setattr(nbrk.httpx, "get", lambda *a, **k: _Resp())
    assert nbrk.load(date(2026, 9, 27)) == 3
    rates = {r.currency_code: r.rate for r in ExchangeRate.objects.all()}
    assert rates == {"USD": Decimal("470.120000"), "RUB": Decimal("5.430000"),
                     "KGS": Decimal("5.320000")}


@pytest.mark.django_db
def test_manual_rate_wins(monkeypatch):
    ExchangeRate.objects.create(currency_code="USD", on_date=date(2026, 9, 27),
                                rate=Decimal("471.000000"), source="manual")
    monkeypatch.setattr(nbrk.httpx, "get", lambda *a, **k: _Resp())
    nbrk.load(date(2026, 9, 27))
    assert ExchangeRate.objects.get(currency_code="USD").rate == Decimal("471.000000")


@pytest.mark.django_db
def test_unavailable_api_is_an_expected_fallback(monkeypatch):
    def boom(*a, **k):
        raise httpx.ConnectError("нет сети")

    monkeypatch.setattr(nbrk.httpx, "get", boom)
    assert nbrk.load(date(2026, 9, 27)) == 0
    assert not ExchangeRate.objects.exists()
