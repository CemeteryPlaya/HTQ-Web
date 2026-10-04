"""Сверка выписки со счетами: чистое ядро (ТЗ §11.3 п.4, BR-070, A4.2).

Здесь только функции без базы: разбор номера счёта в назначении платежа и
распределение суммы по остаткам. Запись сопоставлений — в этом же
подмодуле, отдельными функциями (следующие задачи). Исключение —
агрегат «Оплачено факт» ``paid_fact_by_article`` (CALC-007, D-S4-7) в
конце файла: он только читает.
"""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import CharField, F, Func, Sum, Value
from django.db.models.functions import Upper

from apps.bpp.models import BankImportStatus, PaymentMatch, PaymentMatchState

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


def plain_reg(value: str) -> str:
    """БИН/ИИН или рег. номер для сравнения: без пробельных символов, в
    верхнем регистре. Одно правило на автосверку, кандидатов и дашборд —
    «1234 5678 9012» в выписке и «123456789012» у контрагента совпадают."""
    return "".join((value or "").split()).upper()


def plain_reg_sql(field: str) -> Upper:
    """То же, что ``plain_reg``, выражением SQL над столбцом ``field``."""
    return Upper(Func(F(field), Value(r"\s"), Value(""), Value("g"),
                      function="REGEXP_REPLACE", output_field=CharField()))


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


# ── «Оплачено по банку» и «Оплачено факт» (D-S4-1, CALC-007, D-S4-7) ────

def active_matches():
    """Сопоставления, которые входят в «Оплачено по банку» (D-S4-1): только
    действующие (автоматические без замечаний, ручные и подтверждённые ФД) —
    «на проверке» и отменённые нет; строка выписки не отменена, её загрузка
    не отменена. Одна выборка на всех читателей суммы — дашборд
    (``dashboard/payments``), фильтр реестра счетов по дате платежа
    (``invoices/read``), «Оплачено факт» ниже."""
    return (PaymentMatch.objects
            .filter(state=PaymentMatchState.ACTIVE, line__cancelled_at__isnull=True)
            .exclude(line__bank_import__status=BankImportStatus.CANCELLED))


def paid_fact_by_article(project_id) -> dict[str, Decimal]:
    """``{article_id: оплачено факт}`` по проекту — Σ сопоставленных сумм строк
    выписки по счетам статьи (ТЗ CALC-007). Статьи без оплат — не в ответе.

    - В сумму входят только ``active_matches`` (D-S4-1).
    - Счёт относится к статье своим заголовком ``Invoice.article_id`` (и к
      проекту — ``Invoice.project_id``): счёт выписывается на одну статью
      одного проекта, строки счёта — позиции заявок той же статьи (BR-046).
    - Сумма сопоставления — в валюте счёта, как строки счетов в
      «Задействовано» (CALC-002, ``budget/committed.py``): столбцы одного
      графика считаются в одной валюте.
    """
    rows = (active_matches()
            .filter(invoice__project_id=project_id)
            .order_by()
            .values("invoice__article_id")
            .annotate(total=Sum("amount")))
    return {str(row["invoice__article_id"]): _money(row["total"]) for row in rows}
