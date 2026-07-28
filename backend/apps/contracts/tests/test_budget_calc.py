"""Арифметика бюджета — ядро модуля.

Всё, что здесь проверяется, держит одно утверждение: остаток ВЫВОДИТСЯ из
договоров, а не хранится. Поэтому тесты меняют договоры и смотрят на
остаток, ни разу не записывая его напрямую.
"""

from decimal import Decimal

import pytest

from apps.contracts.models import AgreementStatus
from apps.contracts.services import budget_calc
from apps.contracts.services.budget_calc import BudgetExceeded

from .helpers import make_agreement, make_budget, make_counterparty


@pytest.mark.django_db
def test_empty_budget_is_fully_available():
    budget = make_budget(amount="5000000.00")
    totals = budget_calc.totals_for(budget)
    assert totals["allocated"] == Decimal("5000000.00")
    assert totals["committed"] == Decimal("0.00")
    assert totals["remaining"] == Decimal("5000000.00")


@pytest.mark.django_db
def test_signed_agreement_reduces_remaining():
    budget = make_budget(amount="5000000.00")
    make_agreement(budget=budget, amount="400000.00", status=AgreementStatus.SIGNED)

    totals = budget_calc.totals_for(budget)
    assert totals["committed"] == Decimal("400000.00")
    assert totals["remaining"] == Decimal("4600000.00")


@pytest.mark.django_db
def test_draft_does_not_consume_budget():
    """Черновик виден в списке договоров, но лимит не занимает — иначе
    брошенные черновики молча съедали бы бюджет."""
    budget = make_budget(amount="1000000.00")
    make_agreement(budget=budget, amount="900000.00", status=AgreementStatus.DRAFT)

    assert budget_calc.remaining_for(budget) == Decimal("1000000.00")


@pytest.mark.django_db
def test_terminated_agreement_releases_budget():
    budget = make_budget(amount="1000000.00")
    agreement = make_agreement(budget=budget, amount="600000.00",
                               status=AgreementStatus.SIGNED)
    assert budget_calc.remaining_for(budget) == Decimal("400000.00")

    agreement.status = AgreementStatus.TERMINATED
    agreement.save(update_fields=["status"])
    assert budget_calc.remaining_for(budget) == Decimal("1000000.00")


@pytest.mark.django_db
def test_committed_map_batches_and_omits_empty_budgets():
    """Список бюджетов не должен делать запрос на строку: занятость всех
    строк приходит одним агрегатом, а строки без договоров в него не
    попадают (вызывающий берёт их через .get(id, ZERO))."""
    used = make_budget(amount="1000000.00")
    unused = make_budget(administrator=used.administrator,
                         program=used.program, period_year=2027,
                         amount="2000000.00")
    make_agreement(budget=used, amount="250000.00", status=AgreementStatus.APPROVED)

    result = budget_calc.committed_map([used.pk, unused.pk])
    assert result == {used.pk: Decimal("250000.00")}
    assert result.get(unused.pk, budget_calc.ZERO) == Decimal("0.00")


@pytest.mark.django_db
def test_committed_sums_only_committing_statuses():
    budget = make_budget(amount="10000000.00")
    counterparty = make_counterparty(country=budget.administrator.country)
    for index, status in enumerate(AgreementStatus.values):
        make_agreement(budget=budget, counterparty=counterparty,
                       number=f"Д-{index}", amount="100000.00", status=status)

    expected = Decimal("100000.00") * len(budget_calc.COMMITTING_STATUSES)
    assert budget_calc.committed_for(budget.pk) == expected


@pytest.mark.django_db
def test_check_capacity_raises_when_over_budget():
    budget = make_budget(amount="1000000.00")
    make_agreement(budget=budget, amount="800000.00", status=AgreementStatus.SIGNED)

    with pytest.raises(BudgetExceeded) as exc:
        budget_calc.check_capacity(budget, Decimal("300000.00"))
    assert exc.value.remaining == Decimal("200000.00")

    # Ровно в остаток — помещается.
    budget_calc.check_capacity(budget, Decimal("200000.00"))


@pytest.mark.django_db
def test_exclude_agreement_id_lets_an_agreement_grow():
    """При редактировании договора его СОБСТВЕННАЯ старая сумма не должна
    считаться чужой занятостью — иначе увеличение суммы на копейку почти
    всегда падало бы на проверке лимита."""
    budget = make_budget(amount="1000000.00")
    agreement = make_agreement(budget=budget, amount="900000.00",
                               status=AgreementStatus.SIGNED)

    with pytest.raises(BudgetExceeded):
        budget_calc.check_capacity(budget, Decimal("950000.00"))

    budget_calc.check_capacity(budget, Decimal("950000.00"),
                               exclude_agreement_id=agreement.pk)
