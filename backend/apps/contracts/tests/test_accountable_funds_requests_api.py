"""Заявки на подотчётные средства: создание, Signoff и отметка оплаты."""

from datetime import date

import pytest
from django.test import Client

from apps.contracts.models import AccountableFundsRequestStatus
from apps.contracts.services.accountable_funds_request_service import ACCOUNTING_PAYMENT_PERMISSION
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
    from apps.contracts.models import AccountableFundsRequest

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
