"""Публичный ``interface.py`` — контракт для соседних аппок.

Проверяется то, ради чего этот файл существует: наружу уходят простые
``dict``, а не ORM-объекты, и остаток в них совпадает с тем, что считает
``budget_calc`` (то есть сосед не получит собственную версию арифметики).
"""

from decimal import Decimal

import pytest
from django.db.models import Model

from apps.contracts import interface
from apps.contracts.models import AgreementStatus

from .helpers import make_agreement, make_budget


@pytest.mark.django_db
def test_budget_summary_matches_computed_remaining():
    budget = make_budget(amount="5000000.00")
    make_agreement(budget=budget, amount="400000.00", status=AgreementStatus.SIGNED)

    summary = interface.get_budget_summary(budget.pk)
    assert not isinstance(summary, Model)
    assert summary["allocated"] == Decimal("5000000.00")
    assert summary["committed"] == Decimal("400000.00")
    assert summary["remaining"] == Decimal("4600000.00")
    assert summary["expense_item"] == budget.program.expense_item


@pytest.mark.django_db
def test_missing_rows_return_none_not_raise():
    assert interface.get_budget_summary(9999) is None
    assert interface.get_budget_remaining(9999) is None
    assert interface.get_agreement_brief(9999) is None


@pytest.mark.django_db
def test_agreement_brief_is_a_plain_dict():
    budget = make_budget()
    agreement = make_agreement(budget=budget, amount="1000.00",
                               status=AgreementStatus.SIGNED)

    brief = interface.get_agreement_brief(agreement.pk)
    assert not isinstance(brief, Model)
    assert brief["number"] == agreement.number
    assert brief["counterparty_bin_iin"] == agreement.counterparty.bin_iin
    assert "file_id" not in brief  # служебное наружу не отдаём
