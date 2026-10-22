"""Деньги сравнения (T5.1; спека этапа 5, §1).

Округление — до 0,01 ``ROUND_HALF_UP`` на каждой строке, затем сумма (как
CALC-* БЗО). Сумма поставщика — **к оплате** (S5-03, ответ ФД 20.10): цена
«с НДС» уже включает налог, «без НДС» — и есть сумма к оплате; вычет НДС —
учёт бухгалтера, не функция сравнения. ``gross`` держит это правило в одном
месте.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")


def money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def gross(amount: Decimal, *, with_vat: bool, vat_rate: Decimal | None) -> Decimal:
    """Сумма к оплате по строке предложения (S5-03): как указал поставщик."""
    return money(amount)


def to_kzt(amount: Decimal, rate: Decimal | None) -> Decimal | None:
    return None if rate is None else money(amount * rate)
