"""Personal contracts action queue: ownership, accounting roles and reports."""

from datetime import date

import pytest
from django.test import Client

from apps.contracts.models import (
    AccountableFundsRequest,
    AccountableFundsRequestStatus,
    AdvancePayment,
    AdvancePaymentStatus,
    AdvanceReport,
    ContractPayment,
    CompletionAct,
)
from apps.contracts.tests.helpers import (
    BASE, auth, make_agreement, make_counterparty, make_invoice, make_line, token,
)
from apps.hr.models import Department, Employee, Position
from apps.signoff.models import ApprovalState

pytestmark = pytest.mark.django_db


def _accountant():
    department = Department.objects.create(name="Finance", path="finance-work-queue")
    position = Position.objects.create(
        title="Accountant", department=department, weight=1,
        permissions={"permissions": [
            "contracts.advance_payment.record_payment",
            "contracts.contract_payment.record_payment",
            "contracts.accountable_funds_request.mark_paid",
        ]},
    )
    Employee.objects.create(
        user_id=7, first_name="Queue", last_name="User", email="queue@test",
        department=department, position=position, hire_date=date(2020, 1, 1),
    )


def test_my_tasks_contains_only_current_contracts_actions():
    _accountant()
    line = make_line()
    counterparty = make_counterparty(country=line.budget.administrator.country)
    agreement = make_agreement(
        line=line, counterparty=counterparty, status="draft", created_by=7,
    )
    make_invoice(line=line, counterparty=counterparty, name="Mine", created_by=7)
    make_invoice(line=line, counterparty=counterparty, name="Someone else's", created_by=8)

    advance_payment = AdvancePayment.objects.create(
        agreement=agreement, amount="10.00", created_by=8,
        status=AdvancePaymentStatus.AWAITING_ACCOUNTING,
        approval_state=ApprovalState.APPROVED,
    )
    ContractPayment.objects.create(
        administrator=line.budget.administrator, agreement=agreement, amount="20.00",
        invoice_file_id="invoice", created_by=8,
        status=AdvancePaymentStatus.AWAITING_ACCOUNTING,
        approval_state=ApprovalState.APPROVED,
    )
    CompletionAct.objects.create(
        administrator=line.budget.administrator, agreement=agreement, amount="30.00",
        act_file_id="act", created_by=8,
        status=AdvancePaymentStatus.AWAITING_ACCOUNTING,
        approval_state=ApprovalState.APPROVED,
    )
    awaiting_payment = AccountableFundsRequest.objects.create(
        budget_line=line, amount="40.00", goal="Payment", created_by=8,
        accountable_user_id=8, status=AccountableFundsRequestStatus.AWAITING_ACCOUNTING,
        approval_state=ApprovalState.APPROVED,
    )
    awaiting_report = AccountableFundsRequest.objects.create(
        budget_line=line, amount="50.00", goal="Report", created_by=7,
        accountable_user_id=7, status=AccountableFundsRequestStatus.AWAITING_ADVANCE_REPORT,
        approval_state=ApprovalState.APPROVED,
    )
    AdvanceReport.objects.create(
        accountable_funds_request=awaiting_report, expense_name="Receipt", amount="5.00",
        file_id="report", created_by=7, approval_state=ApprovalState.DRAFT,
    )

    response = Client().get(f"{BASE}/tasks/mine", **auth(token()))

    assert response.status_code == 200, response.content
    items = response.json()
    actions = {(item["action"], item["url"]) for item in items}
    assert ("submit", f"/contracts/agreements/{agreement.pk}") in actions
    assert any(item["action"] == "submit" and item["title"] == "Счёт — Mine" for item in items)
    assert not any(item["title"] == "Счёт — Someone else's" for item in items)
    assert ("record_payment", f"/contracts/advance-payments/{advance_payment.pk}") in actions
    assert ("mark_paid", f"/contracts/accountable-funds-requests/{awaiting_payment.pk}") in actions
    assert ("submit_advance_report", f"/contracts/accountable-funds-requests/{awaiting_report.pk}") in actions
    assert any(item["action"] == "submit" and item["title"] == "Авансовый отчёт — Receipt" for item in items)
    assert sum(item["action"] == "record_payment" for item in items) == 3


def test_my_tasks_does_not_show_accounting_actions_without_permission():
    line = make_line()
    agreement = make_agreement(line=line)
    AdvancePayment.objects.create(
        agreement=agreement, amount="10.00", status=AdvancePaymentStatus.AWAITING_ACCOUNTING,
        approval_state=ApprovalState.APPROVED,
    )

    response = Client().get(f"{BASE}/tasks/mine", **auth(token()))

    assert response.status_code == 200, response.content
    assert response.json() == []
