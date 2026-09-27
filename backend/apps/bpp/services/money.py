"""Деньги модуля: округление и запись суммы для человека (мастер-план §2.5).

``Decimal(18,2)``, округление ``ROUND_HALF_UP`` до 0,01. В текстах ошибок
сумма пишется как в ТЗ §26.1: ``1 250 000,00 KZT`` — пробел между
разрядами, запятая перед копейками.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")


def money(value) -> Decimal:
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def line_amount(qty, price) -> Decimal:
    """Сумма позиции — CALC-004: ``ROUND(Кол-во × Цена, 2)``."""
    return money(Decimal(qty) * Decimal(price))


def fmt(value, currency: str | None = "KZT") -> str:
    text = f"{money(value):,.2f}".replace(",", " ").replace(".", ",")
    return f"{text} {currency}" if currency else text
