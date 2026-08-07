"""Предоплаты на основании договоров: согласование и проведение бухгалтерией."""

from datetime import date

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client

from apps.contracts.models import AgreementStatus
from apps.contracts.services.advance_payment_service import ACCOUNT_PAYMENT_PERMISSION
from apps.contracts.tests.helpers import (
    BASE, admin_token, auth, make_advance_payment, make_agreement, make_line,
    post_json, token,
)
from apps.hr.models import Department, Employee, Position
from apps.signoff.models import ApprovalState


pytestmark = pytest.mark.django_db


def _approved_agreement():
    line = make_line()
    agreement = make_agreement(line=line, status=AgreementStatus.APPROVED)
    agreement.approval_state = ApprovalState.APPROVED
    agreement.save(update_fields=["approval_state"])
    return agreement


def test_create_requires_an_agreement_approved_by_signoff():
    agreement = make_agreement(line=make_line(), status=AgreementStatus.SIGNED)

    blocked = post_json(Client(), f"{BASE}/advance-payments", {
        "agreement_id": agreement.pk, "amount": "100000.00",
    }, **auth(token()))
    assert blocked.status_code == 409, blocked.content
    assert "согласованному договору" in blocked.json()["detail"]

    agreement.approval_state = ApprovalState.APPROVED
    agreement.save(update_fields=["approval_state"])
    ok = post_json(Client(), f"{BASE}/advance-payments", {
        "agreement_id": agreement.pk, "amount": "100000.00",
    }, **auth(token()))
    assert ok.status_code == 201, ok.content
    assert ok.json()["agreement_id"] == agreement.pk
    assert ok.json()["approval_state"] == ApprovalState.DRAFT


def test_payment_order_requires_approved_prepayment_and_accountant(monkeypatch):
    agreement = _approved_agreement()
    payment = make_advance_payment(agreement=agreement)
    client = Client()
    before_approval = client.post(
        f"{BASE}/advance-payments/{payment.pk}/payment-order",
        {"posting_number": "ПР-1", "file": SimpleUploadedFile("order.pdf", b"PDF")}, **auth(admin_token()),
    )
    assert before_approval.status_code == 409, before_approval.content

    payment.approval_state = ApprovalState.APPROVED
    payment.save(update_fields=["approval_state"])
    forbidden = client.post(
        f"{BASE}/advance-payments/{payment.pk}/payment-order",
        {"posting_number": "ПР-1", "file": SimpleUploadedFile("order.pdf", b"PDF")}, **auth(token()),
    )
    assert forbidden.status_code == 403, forbidden.content

    department = Department.objects.create(name="Финансы", path="finance")
    position = Position.objects.create(
        title="Бухгалтер", department=department, weight=101,
        permissions={"permissions": [ACCOUNT_PAYMENT_PERMISSION]},
    )
    Employee.objects.create(
        user_id=7, first_name="Бух", last_name="Галтер", email="accountant@test",
        department=department, position=position, hire_date=date(2020, 1, 1),
    )
    monkeypatch.setattr(
        "apps.contracts.services.advance_payment_service.media.store_file",
        lambda **kwargs: {"id": "payment-order-1"},
    )
    success = client.post(
        f"{BASE}/advance-payments/{payment.pk}/payment-order",
        {"posting_number": "ПР-1", "file": SimpleUploadedFile("order.pdf", b"PDF")}, **auth(token()),
    )
    assert success.status_code == 200, success.content
    assert success.json()["posting_number"] == "ПР-1"
    assert success.json()["payment_order_file_id"] == "payment-order-1"
    assert success.json()["paid_by"] == 7


def test_payment_order_cannot_be_replaced_after_accounting():
    payment = make_advance_payment(agreement=_approved_agreement(),
                                   approval_state=ApprovalState.APPROVED,
                                   payment_order_file_id="old-file", posting_number="ПР-1")
    blocked = Client().post(
        f"{BASE}/advance-payments/{payment.pk}/payment-order",
        {"posting_number": "ПР-2", "file": SimpleUploadedFile("new.pdf", b"PDF")},
        **auth(admin_token()),
    )
    assert blocked.status_code == 409, blocked.content
