"""Курсы Национального банка РК на дату (D-15).

Источник — RSS НБРК ``get_rates.cfm?fdate=ДД.ММ.ГГГГ`` (XML: ``item`` с
``title`` — код валюты, ``description`` — курс, ``quant`` — за сколько
единиц). Храним курс за ОДНУ единицу. Ручной курс ФД на ту же дату
главнее — загрузка его не трогает. Недоступный API — предусмотренная
деградация (``fallback(expected=True)``): курс можно ввести вручную.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import httpx
from defusedxml import ElementTree as ET

from apps.refdata.models import Currency, ExchangeRate, RateSource
from htqweb.fallback import fallback

URL = "https://nationalbank.kz/rss/get_rates.cfm"


def load(on_date: date) -> int:
    """Загрузить курсы на дату; вернуть число записанных валют."""
    try:
        response = httpx.get(URL, params={"fdate": on_date.strftime("%d.%m.%Y")}, timeout=15.0)
        response.raise_for_status()
        root = ET.fromstring(response.text)
    except Exception as exc:
        fallback("refdata.nbrk.fetch_failed", 0, reason="курс НБРК не загружен",
                 exc=exc, expected=True)
        return 0
    known = set(Currency.objects.values_list("code", flat=True))
    written = 0
    for item in root.iter("item"):
        code = (item.findtext("title") or "").strip()
        if code not in known or code == "KZT":
            continue
        rate = Decimal((item.findtext("description") or "0").strip())
        quant = Decimal((item.findtext("quant") or "1").strip() or "1")
        per_unit = (rate / quant).quantize(Decimal("0.000001"))
        existing = ExchangeRate.objects.filter(currency_code=code, on_date=on_date).first()
        if existing is not None and existing.source == RateSource.MANUAL:
            continue
        ExchangeRate.objects.update_or_create(
            currency_code=code, on_date=on_date,
            defaults={"rate": per_unit, "source": RateSource.NBRK})
        written += 1
    return written
