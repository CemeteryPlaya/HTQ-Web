"""Оплаты по договорам: счёт, согласование и бухгалтерское проведение."""

from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.http import Http404
from django.utils import timezone

from apps.contracts.models import (
    Administrator, AdvancePayment, AdvancePaymentStatus, Agreement, AgreementStatus,
    CompletionAct, ContractPayment,
)
from apps.media_files import interface as media
from apps.signoff import interface as signoff


ACCOUNT_PAYMENT_PERMISSION = "contracts.contract_payment.record_payment"
ZERO = Decimal("0.00")
_RELATED = ("administrator", "agreement", "agreement__counterparty",
            "agreement__budget_line__budget")
_ALLOWED_TRANSITIONS = {
    AdvancePaymentStatus.DRAFT: frozenset({AdvancePaymentStatus.ON_REVIEW}),
    AdvancePaymentStatus.ON_REVIEW: frozenset({
        AdvancePaymentStatus.DRAFT, AdvancePaymentStatus.AWAITING_ACCOUNTING,
    }),
    AdvancePaymentStatus.AWAITING_ACCOUNTING: frozenset({
        AdvancePaymentStatus.DRAFT, AdvancePaymentStatus.CLOSED,
    }),
    AdvancePaymentStatus.CLOSED: frozenset(),
}


class ContractPaymentRuleViolation(Exception):
    """Нарушено правило жизненного цикла оплаты по договору."""


def get_contract_payment_or_404(payment_id: int, *, lock: bool = False) -> ContractPayment:
    query = ContractPayment.objects.select_related(*_RELATED)
    if lock:
        query = query.select_for_update()
    payment = query.filter(pk=payment_id).first()
    if payment is None:
        raise Http404("Оплата по договору не найдена")
    return payment


def _eligible_agreement(agreement_id: int) -> Agreement:
    agreement = (Agreement.objects.select_for_update()
                 .select_related("counterparty", "budget_line__budget")
                 .filter(pk=agreement_id).first())
    if agreement is None:
        raise Http404("Договор не найден")
    if not agreement.is_approved or agreement.status not in (
        AgreementStatus.APPROVED, AgreementStatus.SIGNED,
    ):
        raise ContractPaymentRuleViolation(
            "Оплату можно оформить только по действующему согласованному договору"
        )
    return agreement


def paid_amount_for_agreement(agreement_id: int) -> Decimal:
    advance = (AdvancePayment.objects
               .filter(agreement_id=agreement_id, status=AdvancePaymentStatus.CLOSED)
               .aggregate(total=Sum("amount"))["total"] or ZERO)
    payments = (ContractPayment.objects
                .filter(agreement_id=agreement_id, status=AdvancePaymentStatus.CLOSED)
                .aggregate(total=Sum("amount"))["total"] or ZERO)
    acts = (CompletionAct.objects
            .filter(agreement_id=agreement_id, status=AdvancePaymentStatus.CLOSED)
            .aggregate(total=Sum("amount"))["total"] or ZERO)
    return advance + payments + acts


def check_agreement_capacity(agreement: Agreement, amount) -> None:
    remaining = agreement.amount - paid_amount_for_agreement(agreement.pk)
    if amount > remaining:
        raise ContractPaymentRuleViolation(
            f"Сумма оплаты {amount} превышает остаток договора {agreement.number}: доступно {remaining}"
        )


def serialize_contract_payment(payment: ContractPayment) -> dict:
    agreement = payment.agreement
    return {
        "id": payment.pk,
        "administrator_id": payment.administrator_id,
        "administrator_name": payment.administrator.display_name,
        "agreement_id": agreement.pk,
        "agreement_number": agreement.number,
        "agreement_name": agreement.name,
        "counterparty_name": agreement.counterparty.name,
        "amount": payment.amount,
        "currency": agreement.currency,
        "invoice_file_id": payment.invoice_file_id,
        "status": payment.status,
        "approval_state": payment.approval_state,
        "payment_order_file_id": payment.payment_order_file_id,
        "posting_number": payment.posting_number,
        "paid_by": payment.paid_by,
        "paid_at": payment.paid_at,
        "created_by": payment.created_by,
        "created_at": payment.created_at,
        "updated_at": payment.updated_at,
    }


def list_contract_payments(*, administrator_id: int | None = None,
                           agreement_id: int | None = None,
                           awaiting_payment: bool | None = None):
    query = ContractPayment.objects.select_related(*_RELATED)
    if administrator_id is not None:
        query = query.filter(administrator_id=administrator_id)
    if agreement_id is not None:
        query = query.filter(agreement_id=agreement_id)
    if awaiting_payment is True:
        query = query.filter(status=AdvancePaymentStatus.AWAITING_ACCOUNTING)
    return list(query)


@transaction.atomic
def create_contract_payment(*, administrator_id: int, agreement_id: int, amount,
                            invoice_data: bytes, invoice_filename: str, invoice_mime: str,
                            created_by: int | None = None) -> ContractPayment:
    agreement = _eligible_agreement(agreement_id)
    administrator = Administrator.objects.filter(pk=administrator_id, is_active=True).first()
    if administrator is None:
        raise ContractPaymentRuleViolation("Администратор не найден или отключён")
    if agreement.budget_line.budget.administrator_id != administrator.pk:
        raise ContractPaymentRuleViolation("Выбранный администратор не связан с договором")
    check_agreement_capacity(agreement, amount)
    stored = media.store_file(data=invoice_data, filename=invoice_filename,
                              mime=invoice_mime, scope="generic", owner_id=created_by)
    return ContractPayment.objects.create(
        administrator=administrator, agreement=agreement, amount=amount,
        invoice_file_id=str(stored["id"]), created_by=created_by,
    )


@transaction.atomic
def submit_for_approval(payment_id: int, *, actor_id: int | None = None) -> dict:
    payment = get_contract_payment_or_404(payment_id, lock=True)
    agreement = _eligible_agreement(payment.agreement_id)
    if payment.status != AdvancePaymentStatus.DRAFT:
        raise ContractPaymentRuleViolation("На согласование можно отправить только черновик оплаты")
    check_agreement_capacity(agreement, payment.amount)
    if payment.approval_state not in signoff.ApprovalState.editable():
        payment.assert_editable()
    return signoff.start_process(subject_type=ContractPayment.SIGNOFF_SUBJECT_TYPE,
                                 subject_id=payment.pk, initiator_id=actor_id, enrich=True)


def change_status(payment_id: int, new_status: str) -> ContractPayment:
    payment = get_contract_payment_or_404(payment_id)
    if new_status not in AdvancePaymentStatus.values:
        raise ContractPaymentRuleViolation(f"Неизвестный статус оплаты: {new_status}")
    if new_status == payment.status:
        return payment
    if new_status not in _ALLOWED_TRANSITIONS[payment.status]:
        raise ContractPaymentRuleViolation("Переход статуса оплаты не разрешён")
    payment.status = new_status
    payment.save(update_fields=["status", "updated_at"])
    return payment


@transaction.atomic
def record_payment(payment_id: int, *, posting_number: str, data: bytes,
                   filename: str, mime: str, actor_id: int,
                   is_elevated: bool = False) -> ContractPayment:
    # Lock this row before checking its state: two accountants must not both post it.
    payment = get_contract_payment_or_404(payment_id, lock=True)
    agreement = _eligible_agreement(payment.agreement_id)
    if not payment.is_approved or payment.status != AdvancePaymentStatus.AWAITING_ACCOUNTING:
        raise ContractPaymentRuleViolation("Оформить платёж можно только после согласования оплаты")
    if payment.payment_order_file_id or payment.posting_number:
        raise ContractPaymentRuleViolation("Оплата уже проведена")
    check_agreement_capacity(agreement, payment.amount)
    if not is_elevated:
        from apps.hr import interface as hr
        if not hr.user_has_permission(actor_id, ACCOUNT_PAYMENT_PERMISSION):
            raise PermissionError("Требуется роль «Бухгалтер»")
    stored = media.store_file(data=data, filename=filename, mime=mime,
                              scope="generic", owner_id=actor_id)
    payment.payment_order_file_id = str(stored["id"])
    payment.posting_number = posting_number
    payment.paid_by = actor_id
    payment.paid_at = timezone.now()
    payment.status = AdvancePaymentStatus.CLOSED
    payment.save(update_fields=["payment_order_file_id", "posting_number", "paid_by",
                                "paid_at", "status", "updated_at"])
    return get_contract_payment_or_404(payment.pk)


def invoice_url(payment: ContractPayment) -> str | None:
    return media.get_file_url(payment.invoice_file_id) if payment.invoice_file_id else None


def payment_order_url(payment: ContractPayment) -> str | None:
    return media.get_file_url(payment.payment_order_file_id) if payment.payment_order_file_id else None
