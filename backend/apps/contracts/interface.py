"""Публичный API аппки contracts для ДРУГИХ аппок.

Единственный способ, которым сосед имеет право обращаться к contracts.
Прямой импорт ``apps.contracts.models`` / ``apps.contracts.services`` из
другой аппки запрещён и ловится тестом
``apps/core/tests/test_app_isolation.py``.

Сейчас потребителей нет — модуль ни от кого не вызывается. Функции ниже
заведены не «на всякий случай», а потому что два вызова уже просматриваются:
``apps.approvals`` при подключении согласования договоров и любой отчётный
раздел, которому нужен остаток бюджета. Обе следуют контракту, общему для
всех ``interface.py`` в репозитории:

- ``require_service("contracts")`` первой строкой — если аппка выключена,
  вызывающий получает ``ServiceDisabled``, который ``api_view`` превращает в
  503-конверт, а не в голый 500;
- возвращаются простые ``dict``/``list``/``Decimal``, никогда ORM-объекты —
  сосед не должен получить возможность мутировать чужие строки.
"""

from __future__ import annotations

from decimal import Decimal

from apps.contracts.models import Agreement, Budget, BudgetLine, Invoice
from apps.contracts.services import budget_calc
from apps.core.services import require_service


def get_budget_summary(budget_id: int) -> dict | None:
    """Бюджет ЦЕЛИКОМ: ``{id, administrator_name, period_year, currency,
    status, allocated, committed, remaining, lines: [...]}`` или ``None``,
    если бюджета нет.

    ``allocated`` — сумма строк: хранимого поля под неё нет
    (``budget_calc``). Строки отдаются простыми словарями — сосед не должен
    получить ORM-объект, который можно сохранить.
    """
    require_service("contracts")

    budget = (Budget.objects
              .select_related("administrator", "administrator__country")
              .prefetch_related("lines__program")
              .filter(pk=budget_id).first())
    if budget is None:
        return None

    lines = list(budget.lines.all())
    committed = budget_calc.committed_map([line.pk for line in lines])
    totals = budget_calc.totals_for_budget(lines, committed=committed)
    return {
        "id": budget.pk,
        "administrator_name": budget.administrator.display_name,
        "period_year": budget.period_year,
        "currency": budget.currency,
        "status": budget.status,
        "allocated": totals["allocated"],
        "committed": totals["committed"],
        "remaining": totals["remaining"],
        "lines": [
            {
                "id": line.pk,
                "program_name": line.program.display_name,
                "expense_item": line.program.expense_item,
                "amount": line.amount,
                "committed": committed.get(line.pk, budget_calc.ZERO),
                "remaining": line.amount - committed.get(line.pk, budget_calc.ZERO),
            }
            for line in lines
        ],
    }


def get_budget_line_remaining(budget_line_id: int) -> Decimal | None:
    """Остаток одной СТРОКИ — для проверок вида «хватит ли денег».

    Спрашивать остаток бюджета целиком для такой проверки нельзя: лимит
    расходуется по программам, и свободные деньги у соседней программы не
    делают договор допустимым (см. ``budget_calc.check_capacity``).
    """
    require_service("contracts")

    line = BudgetLine.objects.filter(pk=budget_line_id).first()
    if line is None:
        return None
    return budget_calc.remaining_for(line)


def get_agreement_brief(agreement_id: int) -> dict | None:
    """Минимальная карточка договора для чужого UI (список согласований,
    карточка заявки): без файла, без служебных меток."""
    require_service("contracts")

    agreement = (Agreement.objects
                 .select_related("counterparty", "budget_line")
                 .filter(pk=agreement_id).first())
    if agreement is None:
        return None

    return {
        "id": agreement.pk,
        "number": agreement.number,
        "name": agreement.name,
        "counterparty_name": agreement.counterparty.name,
        "counterparty_bin_iin": agreement.counterparty.bin_iin,
        "amount": agreement.amount,
        "currency": agreement.currency,
        "payment_type": agreement.payment_type,
        "status": agreement.status,
        "budget_line_id": agreement.budget_line_id,
        "budget_id": agreement.budget_line.budget_id,
        "signed_date": agreement.signed_date,
    }


def get_invoice_brief(invoice_id: int) -> dict | None:
    """Минимальная карточка счёта на оплату для чужого UI (список
    согласований, когда согласование счёта подключат): без файла, без
    служебных меток. Парная к ``get_agreement_brief``."""
    require_service("contracts")

    invoice = (Invoice.objects
               .select_related("counterparty", "budget_line")
               .filter(pk=invoice_id).first())
    if invoice is None:
        return None

    return {
        "id": invoice.pk,
        "name": invoice.name,
        "counterparty_name": invoice.counterparty.name,
        "counterparty_bin_iin": invoice.counterparty.bin_iin,
        "amount": invoice.amount,
        "currency": invoice.currency,
        "status": invoice.status,
        "budget_line_id": invoice.budget_line_id,
        "budget_id": invoice.budget_line.budget_id,
    }
