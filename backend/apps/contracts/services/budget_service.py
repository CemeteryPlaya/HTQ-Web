"""CRUD бюджетных строк + сборка их представления с остатком.

Арифметику не дублирует — «законтрактовано»/«остаток» приходят из
``budget_calc``, единственного места, где они считаются.
"""

from __future__ import annotations

from django.http import Http404

from apps.contracts.models import Budget
from apps.contracts.services import budget_calc
from apps.contracts.services.reference_service import (
    ReferenceConflict,
    conflict_as,
    delete_protected,
    get_administrator_or_404,
    get_program_or_404,
)


def list_budgets(*, administrator_id: int | None = None, program_id: int | None = None,
                 period_year: int | None = None, status: str | None = None) -> list[dict]:
    """Список бюджетов, уже с ``allocated``/``committed``/``remaining``.

    Занятость всех строк берётся ОДНИМ агрегирующим запросом
    (``budget_calc.committed_map``), а не по запросу на строку — иначе
    список из 200 бюджетов означал бы 201 запрос.
    """
    query = Budget.objects.select_related("administrator", "program")
    if administrator_id is not None:
        query = query.filter(administrator_id=administrator_id)
    if program_id is not None:
        query = query.filter(program_id=program_id)
    if period_year is not None:
        query = query.filter(period_year=period_year)
    if status is not None:
        query = query.filter(status=status)

    budgets = list(query)
    committed = budget_calc.committed_map([b.pk for b in budgets])
    return [
        serialize_budget(b, committed=committed.get(b.pk, budget_calc.ZERO))
        for b in budgets
    ]


def get_budget_or_404(budget_id: int) -> Budget:
    budget = Budget.objects.select_related("administrator", "program").filter(pk=budget_id).first()
    if budget is None:
        raise Http404("Бюджет не найден")
    return budget


def serialize_budget(budget: Budget, *, committed=None) -> dict:
    totals = budget_calc.totals_for(budget, committed=committed)
    return {
        "id": budget.pk,
        "administrator_id": budget.administrator_id,
        "administrator_name": budget.administrator.full_name,
        "program_id": budget.program_id,
        "program_name": budget.program.name,
        "expense_item": budget.program.expense_item,
        "amount": budget.amount,
        "currency": budget.currency,
        "period_year": budget.period_year,
        "status": budget.status,
        "note": budget.note,
        "committed": totals["committed"],
        "remaining": totals["remaining"],
        "created_at": budget.created_at,
        "updated_at": budget.updated_at,
    }


def create_budget(*, administrator_id: int, program_id: int, amount,
                  period_year: int, currency: str = "KZT", note: str = "") -> Budget:
    get_administrator_or_404(administrator_id)
    get_program_or_404(program_id)
    with conflict_as("Бюджет на эту связку «администратор / программа / год» уже существует"):
        return Budget.objects.create(
            administrator_id=administrator_id, program_id=program_id,
            amount=amount, period_year=period_year, currency=currency, note=note,
        )


def update_budget(budget_id: int, **fields) -> Budget:
    budget = get_budget_or_404(budget_id)

    if fields.get("administrator_id") is not None:
        get_administrator_or_404(fields["administrator_id"])
    if fields.get("program_id") is not None:
        get_program_or_404(fields["program_id"])

    new_amount = fields.get("amount")
    if new_amount is not None:
        # Урезать бюджет ниже уже законтрактованного нельзя: остаток стал бы
        # отрицательным, и «свободно −300 000 ₸» — это не состояние, из
        # которого система умеет выходить. Расторгните лишние договоры
        # раньше, чем урезать строку.
        committed = budget_calc.committed_for(budget.pk)
        if new_amount < committed:
            raise ReferenceConflict(
                f"Нельзя уменьшить бюджет до {new_amount}: "
                f"уже законтрактовано {committed}"
            )

    new_currency = fields.get("currency")
    if new_currency is not None and new_currency != budget.currency:
        if budget.agreements.exists():
            raise ReferenceConflict(
                "Нельзя сменить валюту бюджета, к которому уже привязаны договоры"
            )

    changed = [key for key, value in fields.items() if value is not None]
    for key in changed:
        setattr(budget, key, fields[key])
    if changed:
        with conflict_as("Бюджет на эту связку «администратор / программа / год» уже существует"):
            budget.save()
    return budget


def delete_budget(budget_id: int) -> None:
    delete_protected(get_budget_or_404(budget_id),
                     "К бюджету привязаны договоры — закройте строку "
                     "(status=closed) вместо удаления")
