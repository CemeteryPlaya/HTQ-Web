"""Предоплаты на основании договоров.

Предоплату можно завести только по договору, который signoff уже одобрил.
После одобрения самой предоплаты бухгалтер отдельным действием прикладывает
платёжное поручение и номер проводки. Это исполнение платежа, не этап
согласования, поэтому оно намеренно не живёт в ``apps.signoff``.
"""

from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.http import Http404
from django.utils import timezone

from apps.contracts.models import (
    AdvancePayment, AdvancePaymentStatus, Agreement, AgreementStatus, CompletionAct, ContractPayment,
)
from apps.contracts.services.reference_service import conflict_as
from apps.media_files import interface as media
from apps.signoff import interface as signoff


ACCOUNT_PAYMENT_PERMISSION = "contracts.advance_payment.record_payment"
ZERO = Decimal("0.00")


ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    AdvancePaymentStatus.DRAFT: frozenset({AdvancePaymentStatus.ON_REVIEW}),
    AdvancePaymentStatus.ON_REVIEW: frozenset({
        AdvancePaymentStatus.DRAFT, AdvancePaymentStatus.AWAITING_ACCOUNTING,
    }),
    AdvancePaymentStatus.AWAITING_ACCOUNTING: frozenset({
        AdvancePaymentStatus.DRAFT, AdvancePaymentStatus.CLOSED,
    }),
    AdvancePaymentStatus.CLOSED: frozenset(),
}


class AdvancePaymentRuleViolation(Exception):
    """Нарушено правило жизненного цикла предоплаты."""


_RELATED = ("agreement", "agreement__counterparty")


def get_advance_payment_or_404(payment_id: int, *, lock: bool = False) -> AdvancePayment:
    query = AdvancePayment.objects.select_related(*_RELATED)
    if lock:
        query = query.select_for_update()
    payment = query.filter(pk=payment_id).first()
    if payment is None:
        raise Http404("Предоплата не найдена")
    return payment


def _approved_agreement(agreement_id: int) -> Agreement:
    agreement = (Agreement.objects.select_for_update().select_related("counterparty")
                 .filter(pk=agreement_id).first())
    if agreement is None:
        raise Http404("Договор не найден")
    if (not agreement.is_approved or agreement.status not in
            (AgreementStatus.APPROVED, AgreementStatus.SIGNED)):
        raise AdvancePaymentRuleViolation(
            "Предоплату можно оформить только по согласованному договору"
        )
    return agreement


def closed_amount_for_agreement(agreement_id: int) -> Decimal:
    """Сумма фактически проведённой предоплаты по договору."""
    return (AdvancePayment.objects
            .filter(agreement_id=agreement_id, status=AdvancePaymentStatus.CLOSED)
            .aggregate(total=Sum("amount"))["total"] or ZERO)


def total_paid_amount_for_agreement(agreement_id: int) -> Decimal:
    """Все проведённые деньги по договору: аванс и обычные оплаты."""
    advance = closed_amount_for_agreement(agreement_id)
    payments = (ContractPayment.objects
                .filter(agreement_id=agreement_id, status=AdvancePaymentStatus.CLOSED)
                .aggregate(total=Sum("amount"))["total"] or ZERO)
    acts = (CompletionAct.objects
            .filter(agreement_id=agreement_id, status=AdvancePaymentStatus.CLOSED)
            .aggregate(total=Sum("amount"))["total"] or ZERO)
    return advance + payments + acts


def check_agreement_capacity(agreement: Agreement, amount) -> None:
    remaining = agreement.amount - total_paid_amount_for_agreement(agreement.pk)
    if amount > remaining:
        raise AdvancePaymentRuleViolation(
            f"Сумма предоплаты {amount} превышает остаток договора "
            f"{agreement.number}: доступно {remaining}"
        )


def serialize_advance_payment(payment: AdvancePayment) -> dict:
    agreement = payment.agreement
    return {
        "id": payment.pk,
        "agreement_id": agreement.pk,
        "agreement_number": agreement.number,
        "agreement_name": agreement.name,
        "counterparty_name": agreement.counterparty.name,
        "amount": payment.amount,
        "currency": agreement.currency,
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


def list_advance_payments(*, agreement_id: int | None = None,
                          awaiting_payment: bool | None = None):
    query = AdvancePayment.objects.select_related(*_RELATED)
    if agreement_id is not None:
        query = query.filter(agreement_id=agreement_id)
    if awaiting_payment is True:
        query = query.filter(status=AdvancePaymentStatus.AWAITING_ACCOUNTING)
    return list(query)


@transaction.atomic
def create_advance_payment(*, agreement_id: int, amount, created_by: int | None = None):
    agreement = _approved_agreement(agreement_id)
    if AdvancePayment.objects.filter(agreement_id=agreement.pk).exists():
        raise AdvancePaymentRuleViolation(
            f"По договору {agreement.number} уже создана предоплата"
        )
    check_agreement_capacity(agreement, amount)
    with conflict_as(f"По договору {agreement.number} уже создана предоплата"):
        return AdvancePayment.objects.create(
            agreement=agreement, amount=amount, status=AdvancePaymentStatus.DRAFT,
            created_by=created_by,
        )


@transaction.atomic
def submit_for_approval(payment_id: int, *, actor_id: int | None = None) -> dict:
    payment = get_advance_payment_or_404(payment_id, lock=True)
    _approved_agreement(payment.agreement_id)
    if payment.status != AdvancePaymentStatus.DRAFT:
        raise AdvancePaymentRuleViolation(
            "На согласование можно отправить только предоплату в статусе «Черновик»"
        )
    if payment.approval_state not in signoff.ApprovalState.editable():
        payment.assert_editable()
    return signoff.start_process(
        subject_type=AdvancePayment.SIGNOFF_SUBJECT_TYPE,
        subject_id=payment.pk,
        initiator_id=actor_id,
        enrich=True,
    )


def change_status(payment_id: int, new_status: str) -> AdvancePayment:
    """Сдвинуть предоплату по её машине статусов.

    Этот путь используют только колбэки signoff и оформление бухгалтерией;
    отдельного ручного HTTP-перехода нет.
    """
    payment = get_advance_payment_or_404(payment_id)
    if new_status not in AdvancePaymentStatus.values:
        raise AdvancePaymentRuleViolation(f"Неизвестный статус предоплаты: {new_status}")
    if new_status == payment.status:
        return payment
    if new_status not in ALLOWED_TRANSITIONS[payment.status]:
        raise AdvancePaymentRuleViolation(
            f"Переход «{AdvancePaymentStatus(payment.status).label}» → "
            f"«{AdvancePaymentStatus(new_status).label}» не разрешён"
        )
    payment.status = new_status
    payment.save(update_fields=["status", "updated_at"])
    return payment


@transaction.atomic
def record_payment(payment_id: int, *, posting_number: str, data: bytes,
                   filename: str, mime: str, actor_id: int,
                   is_elevated: bool = False) -> AdvancePayment:
    payment = get_advance_payment_or_404(payment_id, lock=True)
    agreement = _approved_agreement(payment.agreement_id)
    if not payment.is_approved:
        raise AdvancePaymentRuleViolation(
            "Платёжное поручение добавляется только после согласования предоплаты"
        )
    if payment.status != AdvancePaymentStatus.AWAITING_ACCOUNTING:
        raise AdvancePaymentRuleViolation(
            "Оформить платёж можно только для предоплаты, ожидающей бухгалтерию"
        )
    check_agreement_capacity(agreement, payment.amount)
    if payment.payment_order_file_id or payment.posting_number:
        raise AdvancePaymentRuleViolation(
            "Предоплата уже проведена; исправление доступно администратору"
        )

    if not is_elevated:
        # Контракты не импортируют HR напрямую: проверка права идёт через
        # публичный interface HR. Администратор проходит без привязки к HR.
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
    return get_advance_payment_or_404(payment.pk)


def payment_order_url(payment: AdvancePayment) -> str | None:
    if not payment.payment_order_file_id:
        return None
    return media.get_file_url(payment.payment_order_file_id)
