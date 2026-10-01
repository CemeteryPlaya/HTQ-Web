"""CALC-013 и суммы альтернативного предложения — чистые функции, без БД.

Деньги — ``Decimal``, ``ROUND_HALF_UP`` до копеек (``services/money.py``).
Сумма АП — Σ сумм строк, каждая строка округляется отдельно (CALC-004),
как у счёта и договора. Цены — с НДС, если он есть (D-S5-3).
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from apps.bpp.services.money import line_amount, money

__all__ = ["offer_amount", "saving", "source_part", "source_price"]

_PCT = Decimal("0.01")


def offer_amount(lines: list[tuple[Decimal, Decimal]]) -> Decimal:
    """Σ qty × price по строкам АП (цены с НДС, если он есть)."""
    return money(sum((line_amount(qty, price) for qty, price in lines), Decimal("0")))


def source_part(lines: list[tuple[Decimal, Decimal]]) -> Decimal:
    """Σ сумм выбранных позиций исходного документа (D-S5-3)."""
    return money(sum((amount for _, amount in lines), Decimal("0")))


def saving(source_kzt: Decimal, offer_kzt: Decimal) -> tuple[Decimal, Decimal]:
    """CALC-013: экономия KZT и % от исходной части (0,01 %, ``ROUND_HALF_UP`` —
    как деньги, а не банковское округление контекста ``Decimal``).
    Отрицательная — удорожание; нулевая исходная часть — 0 %, без деления."""
    amount = money(source_kzt - offer_kzt)
    if not source_kzt:
        return amount, Decimal("0.00")
    return amount, (amount * 100 / source_kzt).quantize(_PCT, rounding=ROUND_HALF_UP)


def source_price(amount: Decimal, qty: Decimal) -> Decimal:
    """Цена позиции исходного документа за единицу: сумма / количество, до копеек."""
    return money(amount / qty)
