"""Сверка выписки со счетами: чистое ядро (ТЗ §11.3 п.4, BR-070, A4.2).

Здесь только функции без базы: разбор номера счёта в назначении платежа и
распределение суммы по остаткам. Запись сопоставлений — в этом же
подмодуле, отдельными функциями (следующие задачи).
"""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal

_LOOKALIKES = str.maketrans({"C": "С", "X": "Х", "c": "С", "x": "Х"})
# После перевода в верхний регистр и замены латиницы: «СЧ», затем год из 4 цифр
# и номер из 6. Между частями допускаются пробелы и дефисы (любые тире).
# (?!\d) после номера не даёт взять номер длиннее шести цифр.
_NUMBER = re.compile(r"(?<![А-ЯЁA-Z])СЧ[\s\-‐-―−]*(\d{4})[\s\-‐-―−]*(\d{6})(?!\d)")
_CENT = Decimal("0.01")


def normalize_purpose(text: str) -> str:
    return (text or "").upper().translate(_LOOKALIKES)


def find_numbers(text: str) -> list[str]:
    seen: dict[str, None] = {}
    for year, seq in _NUMBER.findall(normalize_purpose(text)):
        seen.setdefault(f"СЧ-{year}-{seq}", None)
    return list(seen)


def _money(value: Decimal) -> Decimal:
    return Decimal(value).quantize(_CENT, rounding=ROUND_HALF_UP)


def distribute(amount: Decimal,
               remainders: list[tuple[str, Decimal]]) -> tuple[list[tuple[str, Decimal]], bool]:
    """Раскладывает платёж по остаткам счетов в порядке номеров (D-S4-4).

    Каждому счёту достаётся не больше его остатка, пока платёж не кончится.
    Признак ``True`` — сумма платежа равна Σ остатков, распределение
    однозначно; недоплата и переплата — ``False`` (строка уходит на
    проверку, переплату в распределение не кладут).
    """
    if _money(amount) <= 0:
        return [], False
    left = _money(amount)
    total = Decimal("0")
    result: list[tuple[str, Decimal]] = []
    for key, remainder in remainders:
        rest = max(_money(remainder), Decimal("0"))
        total += rest
        part = min(left, rest)
        result.append((key, part))
        left -= part
    return result, _money(amount) == total
