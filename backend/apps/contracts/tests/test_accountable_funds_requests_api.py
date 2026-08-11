"""Заявки на подотчётные средства: создание, Signoff и отметка оплаты."""

from datetime import date

import pytest
from django.test import Client
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.contracts.models import AccountableFundsRequest, AccountableFundsRequestStatus, AdvanceReport
from apps.contracts.services.accountable_funds_request_service import ACCOUNTING_PAYMENT_PERMISSION
from apps.contracts.services import advance_report_service
from apps.contracts.services import budget_calc
from apps.contracts.tests.helpers import BASE, admin_token, auth, make_administrator, make_line, post_json, token
from apps.hr.models import Department, Employee, Position
from apps.signoff.models import ApprovalState


pytestmark = pytest.mark.django_db


def _payload():
    administrator = make_administrator()
    line = make_line(administrator=administrator)
    return {"budget_line_id": line.pk,
            "amount": "100000.00", "goal": "Командировка"}


def test_create_keeps_funds_on_initiators_account():
    response = post_json(Client(), f"{BASE}/accountable-funds-requests", _payload(), **auth(token()))
    assert response.status_code == 201, response.content
    body = response.json()
    assert body["accountable_user_id"] == 7
    assert body["accounting_paid"] is False
    assert body["status"] == AccountableFundsRequestStatus.DRAFT


def test_accounting_paid_is_only_available_after_approval_and_leaves_request_open():
    client = Client()
    created = post_json(client, f"{BASE}/accountable-funds-requests", _payload(), **auth(token()))
    request_id = created.json()["id"]
    before_approval = client.post(f"{BASE}/accountable-funds-requests/{request_id}/accounting-paid", **auth(admin_token()))
    assert before_approval.status_code == 409, before_approval.content

    from apps.contracts.models import AccountableFundsRequest
    request = AccountableFundsRequest.objects.get(pk=request_id)
    request.approval_state = ApprovalState.APPROVED
    request.status = AccountableFundsRequestStatus.AWAITING_ACCOUNTING
    request.save(update_fields=["approval_state", "status"])

    paid = client.post(f"{BASE}/accountable-funds-requests/{request_id}/accounting-paid", **auth(admin_token()))
    assert paid.status_code == 200, paid.content
    body = paid.json()
    assert body["accounting_paid"] is True
    assert body["status"] == AccountableFundsRequestStatus.AWAITING_ADVANCE_REPORT


def test_only_accountant_or_elevated_user_can_mark_paid():
    client = Client()
    created = post_json(client, f"{BASE}/accountable-funds-requests", _payload(), **auth(token()))
    from apps.contracts.models import AccountableFundsRequest
    request = AccountableFundsRequest.objects.get(pk=created.json()["id"])
    request.approval_state = ApprovalState.APPROVED
    request.status = AccountableFundsRequestStatus.AWAITING_ACCOUNTING
    request.save(update_fields=["approval_state", "status"])
    assert client.post(f"{BASE}/accountable-funds-requests/{request.pk}/accounting-paid", **auth(token())).status_code == 403

    department = Department.objects.create(name="Финансы", path="finance-accountable")
    position = Position.objects.create(title="Бухгалтер", department=department, weight=101,
                                       permissions={"permissions": [ACCOUNTING_PAYMENT_PERMISSION]})
    Employee.objects.create(user_id=8, first_name="Бух", last_name="Галтер", email="accountant-accountable@test",
                            department=department, position=position, hire_date=date(2020, 1, 1))
    success = client.post(
        f"{BASE}/accountable-funds-requests/{request.pk}/accounting-paid",
        **auth(token(user_id=8, sub="8")),
    )
    assert success.status_code == 200, success.content


def test_existing_request_can_be_bound_once_to_its_matching_budget_line():
    administrator = make_administrator()
    line = make_line(administrator=administrator, amount="500000.00")
    request = AccountableFundsRequest.objects.create(
        administrator=administrator,
        program=line.program,
        amount="100000.00",
        goal="Первая заявка",
        accountable_user_id=7,
        created_by=7,
        status=AccountableFundsRequestStatus.AWAITING_ACCOUNTING,
        approval_state=ApprovalState.APPROVED,
    )

    bound = post_json(Client(), f"{BASE}/accountable-funds-requests/{request.pk}/budget-line", {
        "budget_line_id": line.pk,
    }, **auth(token()))
    assert bound.status_code == 200, bound.content
    assert bound.json()["budget_line_id"] == line.pk


def _paid_request(*, amount="100000.00"):
    line = make_line(amount="500000.00")
    return AccountableFundsRequest.objects.create(
        budget_line=line, amount=amount, goal="Командировка", accountable_user_id=7,
        created_by=7, approval_state=ApprovalState.APPROVED,
        status=AccountableFundsRequestStatus.AWAITING_ADVANCE_REPORT,
        accounting_paid=True,
    )


def _add_report(client, request, *, expense_name="Проезд", amount="40000.00", **auth_headers):
    return client.post(
        f"{BASE}/accountable-funds-requests/{request.pk}/advance-reports",
        {"expense_name": expense_name, "amount": amount,
         "file": SimpleUploadedFile("report.pdf", b"PDF")},
        **auth_headers,
    )


def test_advance_reports_are_created_only_by_the_initiator_after_payment(monkeypatch):
    request = _paid_request()
    monkeypatch.setattr(
        "apps.contracts.services.advance_report_service.media.store_file",
        lambda **kwargs: {"id": "advance-report-1"},
    )
    forbidden = _add_report(Client(), request, **auth(token(user_id=8, sub="8")))
    assert forbidden.status_code == 403, forbidden.content

    created = _add_report(Client(), request, **auth(token()))
    assert created.status_code == 201, created.content
    body = created.json()
    assert body["expense_name"] == "Проезд"
    assert body["file_id"] == "advance-report-1"
    detail = Client().get(f"{BASE}/accountable-funds-requests/{request.pk}", **auth(token()))
    assert detail.json()["advance_reported_amount"] == "0.00"
    assert detail.json()["remaining_accountable_amount"] == "100000.00"


def test_approved_advance_reports_are_computed_and_close_the_request():
    request = _paid_request()
    first = AdvanceReport.objects.create(
        accountable_funds_request=request, expense_name="Проезд", amount="40000.00",
        file_id="report-1", approval_state=ApprovalState.APPROVED, created_by=7,
    )
    second = AdvanceReport.objects.create(
        accountable_funds_request=request, expense_name="Проживание", amount="60000.00",
        file_id="report-2", approval_state=ApprovalState.PENDING, created_by=7,
    )
    assert advance_report_service.totals_for_request(request) == {
        "reported_amount": 40000, "remaining_amount": 60000,
    }

    # The callback is intentionally tested while the just-approved subject is
    # still pending: this is the order used by the Signoff engine.
    advance_report_service.close_parent_if_fully_reported(second.pk)
    request.refresh_from_db()
    assert request.status == AccountableFundsRequestStatus.CLOSED
    second.approval_state = ApprovalState.APPROVED
    second.save(update_fields=["approval_state"])
    assert advance_report_service.totals_for_request(request) == {
        "reported_amount": 100000, "remaining_amount": 0,
    }
    assert budget_calc.committed_for(request.budget_line_id) == 100000
