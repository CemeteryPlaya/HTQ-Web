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

from .helpers import make_agreement, make_line, make_program


@pytest.mark.django_db
def test_budget_summary_sums_its_lines():
    """Итог бюджета — сумма строк, и он совпадает с тем, что считает
    ``budget_calc``: сосед не получает собственную версию арифметики."""
    line = make_line(amount="5000000.00")
    second = make_line(budget=line.budget, program=make_program(name="Медицина"),
                       amount="2000000.00")
    make_agreement(line=line, amount="400000.00", status=AgreementStatus.SIGNED)

    summary = interface.get_budget_summary(line.budget_id)
    assert not isinstance(summary, Model)
    assert summary["allocated"] == Decimal("7000000.00")
    assert summary["committed"] == Decimal("400000.00")
    assert summary["remaining"] == Decimal("6600000.00")

    # Строки отдаются простыми словарями, каждая со своим остатком.
    lines = {row["id"]: row for row in summary["lines"]}
    assert lines[line.pk]["remaining"] == Decimal("4600000.00")
    assert lines[second.pk]["remaining"] == Decimal("2000000.00")
    assert lines[line.pk]["expense_item"] == line.program.expense_item


@pytest.mark.django_db
def test_line_remaining_is_per_program_not_per_budget():
    """Остаток спрашивается по СТРОКЕ: свободные деньги соседней программы
    в том же бюджете к этой программе отношения не имеют."""
    line = make_line(amount="1000000.00")
    make_line(budget=line.budget, program=make_program(name="Медицина"),
              amount="9000000.00")
    make_agreement(line=line, amount="600000.00", status=AgreementStatus.SIGNED)

    assert interface.get_budget_line_remaining(line.pk) == Decimal("400000.00")


@pytest.mark.django_db
def test_missing_rows_return_none_not_raise():
    assert interface.get_budget_summary(9999) is None
    assert interface.get_budget_line_remaining(9999) is None
    assert interface.get_agreement_brief(9999) is None


@pytest.mark.django_db
def test_agreement_brief_is_a_plain_dict():
    line = make_line()
    agreement = make_agreement(line=line, amount="1000.00",
                               status=AgreementStatus.SIGNED)

    brief = interface.get_agreement_brief(agreement.pk)
    assert not isinstance(brief, Model)
    assert brief["number"] == agreement.number
    assert brief["counterparty_bin_iin"] == agreement.counterparty.bin_iin
    assert "file_id" not in brief  # служебное наружу не отдаём
