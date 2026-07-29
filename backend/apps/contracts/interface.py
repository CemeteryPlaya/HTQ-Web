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

from apps.contracts.models import Agreement, Budget
from apps.contracts.services import budget_calc
from apps.core.services import require_service


def get_budget_summary(budget_id: int) -> dict | None:
    """``{id, administrator_name, program_name, expense_item, period_year,
    allocated, committed, remaining, currency, status}`` или ``None``, если
    бюджетной строки нет."""
    require_service("contracts")

    budget = (Budget.objects
              .select_related("administrator", "administrator__country", "program")
              .filter(pk=budget_id).first())
    if budget is None:
        return None

    totals = budget_calc.totals_for(budget)
    return {
        "id": budget.pk,
        "administrator_name": budget.administrator.display_name,
        "program_name": budget.program.display_name,
        "expense_item": budget.program.expense_item,
        "period_year": budget.period_year,
        "allocated": totals["allocated"],
        "committed": totals["committed"],
        "remaining": totals["remaining"],
        "currency": budget.currency,
        "status": budget.status,
    }


def get_budget_remaining(budget_id: int) -> Decimal | None:
    """Только остаток — для проверок вида «хватит ли денег», без сборки всей
    карточки."""
    require_service("contracts")

    budget = Budget.objects.filter(pk=budget_id).first()
    if budget is None:
        return None
    return budget_calc.remaining_for(budget)


def get_agreement_brief(agreement_id: int) -> dict | None:
    """Минимальная карточка договора для чужого UI (список согласований,
    карточка заявки): без файла, без служебных меток."""
    require_service("contracts")

    agreement = (Agreement.objects.select_related("counterparty", "budget")
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
        "budget_id": agreement.budget_id,
        "signed_date": agreement.signed_date,
    }
