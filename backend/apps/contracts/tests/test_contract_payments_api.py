"""Оплаты по договорам: администратор, лимит, согласование и бухгалтерия."""

from datetime import date

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client

from apps.contracts.models import AdvancePaymentStatus, ContractPayment
from apps.contracts.services.contract_payment_service import ACCOUNT_PAYMENT_PERMISSION
from apps.contracts.tests.helpers import (
    BASE, auth, make_administrator, make_agreement, make_line, token,
)
from apps.hr.models import Department, Employee, Position
from apps.signoff.models import ApprovalState

pytestmark = pytest.mark.django_db


def _approved_agreement():
    agreement = make_agreement(line=make_line())
    agreement.approval_state = ApprovalState.APPROVED
    agreement.save(update_fields=["approval_state"])
    return agreement


def _create(client, agreement, **over):
    data = {
        "administrator_id": str(agreement.budget_line.budget.administrator_id),
        "agreement_id": str(agreement.pk), "amount": "100000.00",
        "invoice": SimpleUploadedFile("invoice.pdf", b"PDF"),
        **over,
    }
    return client.post(f"{BASE}/contract-payments", data, **auth(token()))


def test_contract_payment_requires_the_agreements_administrator_and_invoice(monkeypatch):
    agreement = _approved_agreement()
    monkeypatch.setattr(
        "apps.contracts.services.contract_payment_service.media.store_file",
        lambda **kwargs: {"id": "invoice-1"},
    )
    wrong = _create(Client(), agreement, administrator_id=str(make_administrator().pk))
    assert wrong.status_code == 409, wrong.content

    created = _create(Client(), agreement)
    assert created.status_code == 201, created.content
    assert created.json()["invoice_file_id"] == "invoice-1"
    assert created.json()["status"] == AdvancePaymentStatus.DRAFT


def test_closed_contract_payments_share_the_agreement_limit(monkeypatch):
    agreement = _approved_agreement()
    agreement.amount = "100000.00"
    agreement.save(update_fields=["amount"])
    ContractPayment.objects.create(
        administrator=agreement.budget_line.budget.administrator, agreement=agreement,
        amount="80000.00", invoice_file_id="invoice", approval_state=ApprovalState.APPROVED,
        status=AdvancePaymentStatus.CLOSED,
    )
    monkeypatch.setattr(
        "apps.contracts.services.contract_payment_service.media.store_file",
        lambda **kwargs: {"id": "invoice-2"},
    )
    blocked = _create(Client(), agreement, amount="20000.01")
    assert blocked.status_code == 409, blocked.content


def test_accountant_records_only_an_approved_contract_payment(monkeypatch):
    agreement = _approved_agreement()
    payment = ContractPayment.objects.create(
        administrator=agreement.budget_line.budget.administrator, agreement=agreement,
        amount="100000.00", invoice_file_id="invoice", approval_state=ApprovalState.APPROVED,
        status=AdvancePaymentStatus.AWAITING_ACCOUNTING,
    )
    department = Department.objects.create(name="Финансы", path="finance-payments")
    position = Position.objects.create(title="Бухгалтер", department=department, weight=101,
                                       permissions={"permissions": [ACCOUNT_PAYMENT_PERMISSION]})
    Employee.objects.create(user_id=7, first_name="Бух", last_name="Галтер", email="pay@test",
                            department=department, position=position, hire_date=date(2020, 1, 1))
    monkeypatch.setattr(
        "apps.contracts.services.contract_payment_service.media.store_file",
        lambda **kwargs: {"id": "order-1"},
    )
    response = Client().post(
        f"{BASE}/contract-payments/{payment.pk}/payment-order",
        {"posting_number": "PR-1", "file": SimpleUploadedFile("order.pdf", b"PDF")},
        **auth(token()),
    )
    assert response.status_code == 200, response.content
    assert response.json()["status"] == AdvancePaymentStatus.CLOSED
    assert response.json()["posting_number"] == "PR-1"
