"""Выгрузка раздела для переноса в БЗО (B6.1): вклад каждого документа в
«занято» по правилам ``budget_calc`` — сумма вкладов строки равна
``committed_map``, на этом держится сверка остатков после переноса."""

from __future__ import annotations

from decimal import Decimal

import pytest

from apps.contracts import interface
from apps.contracts.models import (
    AccountableFundsRequest,
    Agreement,
    AgreementDirection,
    AgreementType,
    CompletionAct,
    ContractPayment,
    GoodsInvoice,
)
from apps.signoff import interface as signoff

from .helpers import (
    make_administrator,
    make_advance_payment,
    make_agreement,
    make_budget,
    make_counterparty,
    make_invoice,
    make_line,
    make_program,
)
from .test_approval_wiring import make_user

pytestmark = pytest.mark.django_db


def _payment(model, agreement, amount, status):
    return model.objects.create(administrator=agreement.budget_line.budget.administrator,
                                agreement=agreement, amount=Decimal(amount), status=status)


def test_document_contributions_add_up_to_committed_map():
    admin = make_administrator()
    line = make_line(budget=make_budget(administrator=admin), program=make_program(code="3011"))
    idle = make_line(budget=make_budget(administrator=admin, period_year=2025),
                     program=make_program(name="Связь", code="3012"))
    supplier = make_counterparty(country=admin.country)

    signed = make_agreement(line=line, number="Д-1", amount="400000.00", status="signed",
                            counterparty=supplier)
    make_agreement(line=line, number="Д-2", amount="100000.00", status="draft",
                   counterparty=supplier)
    make_agreement(line=line, number="Д-3", amount="50000.00", status="executed",
                   counterparty=supplier)
    make_agreement(line=line, number="Д-4", amount="70000.00", status="terminated",
                   counterparty=supplier)
    make_agreement(line=line, number="Д-5", amount="30000.00", status="signed",
                   direction=AgreementDirection.INCOME, counterparty=supplier)
    framework = make_agreement(line=line, number="Д-6", amount="0.00", status="signed",
                               contract_type=AgreementType.FRAMEWORK,
                               counterparty=supplier)
    _payment(ContractPayment, framework, "20000.00", "closed")
    make_advance_payment(agreement=framework, amount="10000.00", status="awaiting_accounting")
    _payment(CompletionAct, framework, "5000.00", "draft")
    _payment(GoodsInvoice, framework, "7000.00", "closed")
    # Оплата стандартного договора в «занято» не идёт — его занимает сумма.
    _payment(ContractPayment, signed, "90000.00", "closed")

    make_invoice(line=line, amount="15000.00", status="approved", counterparty=supplier)
    make_invoice(line=line, amount="5000.00", status="paid", counterparty=supplier)
    make_invoice(line=line, amount="9000.00", status="on_review", counterparty=supplier)
    for amount, status, budget_line in (("3000.00", "on_review", line), ("2000.00", "draft", line),
                                        ("4000.00", "awaiting_advance_report", None)):
        AccountableFundsRequest.objects.create(
            budget_line=budget_line, amount=Decimal(amount), goal="Расходники", status=status,
            accountable_user_id=7)

    data = interface.migration_snapshot()

    by_line: dict[int, Decimal] = {}
    for key in ("agreements", "invoices", "payments", "accountable"):
        for row in data[key]:
            if row["budget_line_id"] is not None:
                by_line[row["budget_line_id"]] = (by_line.get(row["budget_line_id"], Decimal("0"))
                                                  + row["committed"])
    expected = Decimal("400000") + 50000 + 20000 + 10000 + 7000 + 15000 + 5000 + 3000
    assert data["committed_by_line"][line.id] == expected
    assert by_line[line.id] == expected
    assert by_line.get(idle.id, Decimal("0")) == data["committed_by_line"].get(idle.id, 0) == 0

    agreements = {row["number"]: row for row in data["agreements"]}
    assert agreements["Д-1"]["items"] == [{"line_no": 1, "name": "Ноутбук", "unit": "шт",
                                          "quantity": Decimal("1.000"),
                                          "amount": Decimal("400000.00")}]
    assert {row["kind"] for row in data["payments"]} == {
        "contract_payment", "advance_payment", "completion_act", "goods_invoice"}
    legacy = next(row for row in data["accountable"] if row["budget_line_id"] is None)
    assert legacy["committed"] == 0          # без строки старый расчёт его не видит
    assert [b["period_year"] for b in data["budgets"]] == [2026, 2025]


def test_revoke_returns_a_running_agreement_to_draft():
    """D-B61-2: документ «На согласовании» переносится черновиком — его
    процесс в старом разделе отзывается, колбэк раздела возвращает черновик."""
    line = make_line()
    agreement = make_agreement(line=line, status="draft")
    approver = make_user("migration-approver")
    signoff.configure_route(subject_type=Agreement.SIGNOFF_SUBJECT_TYPE, name="Договор",
                            stages=[{"order": 1, "name": "ФД", "quorum": "any",
                                     "approver_kind": "users", "user_ids": [approver.id]}])
    signoff.start_process(subject_type=Agreement.SIGNOFF_SUBJECT_TYPE,
                          subject_id=agreement.id, initiator_id=5)
    agreement.refresh_from_db()
    assert agreement.status == "on_review"

    assert interface.revoke_for_migration(Agreement.SIGNOFF_SUBJECT_TYPE,
                                          [agreement.id, agreement.id + 100]) == [agreement.id]
    agreement.refresh_from_db()
    assert agreement.status == "draft"
    assert signoff.get_process_for(Agreement.SIGNOFF_SUBJECT_TYPE, agreement.id)["state"] \
        == "cancelled"
