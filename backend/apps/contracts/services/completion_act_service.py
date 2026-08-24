"""Акты выполненных работ: загрузка акта, согласование и проведение оплаты."""

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


# АВР проводится тем же бухгалтером, что и оплата по договору: отдельная
# роль не нужна, поскольку жизненный цикл и финансовая операция одинаковы.
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


class CompletionActRuleViolation(Exception):
    """Нарушено правило жизненного цикла акта выполненных работ."""


def get_completion_act_or_404(act_id: int, *, lock: bool = False) -> CompletionAct:
    query = CompletionAct.objects.select_related(*_RELATED)
    if lock:
        query = query.select_for_update()
    act = query.filter(pk=act_id).first()
    if act is None:
        raise Http404("Акт выполненных работ не найден")
    return act


def _eligible_agreement(agreement_id: int) -> Agreement:
    agreement = (Agreement.objects.select_for_update()
                 .select_related("counterparty", "budget_line__budget")
                 .filter(pk=agreement_id).first())
    if agreement is None:
        raise Http404("Договор не найден")
    if not agreement.is_approved or agreement.status not in (
        AgreementStatus.APPROVED, AgreementStatus.SIGNED,
    ):
        raise CompletionActRuleViolation(
            "Акт можно оформить только по действующему согласованному договору"
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
        raise CompletionActRuleViolation(
            f"Сумма акта {amount} превышает остаток договора {agreement.number}: "
            f"доступно {remaining}"
        )


def serialize_completion_act(act: CompletionAct) -> dict:
    agreement = act.agreement
    return {
        "id": act.pk,
        "administrator_id": act.administrator_id,
        "administrator_name": act.administrator.display_name,
        "agreement_id": agreement.pk,
        "agreement_number": agreement.number,
        "agreement_name": agreement.name,
        "counterparty_name": agreement.counterparty.name,
        "amount": act.amount,
        "currency": agreement.currency,
        "act_file_id": act.act_file_id,
        "status": act.status,
        "approval_state": act.approval_state,
        "payment_order_file_id": act.payment_order_file_id,
        "posting_number": act.posting_number,
        "paid_by": act.paid_by,
        "paid_at": act.paid_at,
        "created_by": act.created_by,
        "created_at": act.created_at,
        "updated_at": act.updated_at,
    }


def list_completion_acts(*, administrator_id: int | None = None,
                         agreement_id: int | None = None,
                         awaiting_payment: bool | None = None):
    query = CompletionAct.objects.select_related(*_RELATED)
    if administrator_id is not None:
        query = query.filter(administrator_id=administrator_id)
    if agreement_id is not None:
        query = query.filter(agreement_id=agreement_id)
    if awaiting_payment is True:
        query = query.filter(status=AdvancePaymentStatus.AWAITING_ACCOUNTING)
    return list(query)


@transaction.atomic
def create_completion_act(*, administrator_id: int, agreement_id: int, amount,
                          act_data: bytes, act_filename: str, act_mime: str,
                          created_by: int | None = None) -> CompletionAct:
    agreement = _eligible_agreement(agreement_id)
    administrator = Administrator.objects.filter(pk=administrator_id, is_active=True).first()
    if administrator is None:
        raise CompletionActRuleViolation("Администратор не найден или отключён")
    if agreement.budget_line.budget.administrator_id != administrator.pk:
        raise CompletionActRuleViolation("Выбранный администратор не связан с договором")
    check_agreement_capacity(agreement, amount)
    stored = media.store_file(data=act_data, filename=act_filename, mime=act_mime,
                              scope="generic", owner_id=created_by)
    return CompletionAct.objects.create(
        administrator=administrator, agreement=agreement, amount=amount,
        act_file_id=str(stored["id"]), created_by=created_by,
    )


@transaction.atomic
def submit_for_approval(act_id: int, *, actor_id: int | None = None) -> dict:
    act = get_completion_act_or_404(act_id, lock=True)
    agreement = _eligible_agreement(act.agreement_id)
    if act.status != AdvancePaymentStatus.DRAFT:
        raise CompletionActRuleViolation("На согласование можно отправить только черновик акта")
    check_agreement_capacity(agreement, act.amount)
    if act.approval_state not in signoff.ApprovalState.editable():
        act.assert_editable()
    return signoff.start_process(subject_type=CompletionAct.SIGNOFF_SUBJECT_TYPE,
                                 subject_id=act.pk, initiator_id=actor_id, enrich=True)


def change_status(act_id: int, new_status: str) -> CompletionAct:
    act = get_completion_act_or_404(act_id)
    if new_status not in AdvancePaymentStatus.values:
        raise CompletionActRuleViolation(f"Неизвестный статус акта: {new_status}")
    if new_status == act.status:
        return act
    if new_status not in _ALLOWED_TRANSITIONS[act.status]:
        raise CompletionActRuleViolation("Переход статуса акта не разрешён")
    act.status = new_status
    act.save(update_fields=["status", "updated_at"])
    return act


@transaction.atomic
def record_payment(act_id: int, *, posting_number: str, data: bytes,
                   filename: str, mime: str, actor_id: int,
                   is_elevated: bool = False) -> CompletionAct:
    act = get_completion_act_or_404(act_id, lock=True)
    agreement = _eligible_agreement(act.agreement_id)
    if not act.is_approved or act.status != AdvancePaymentStatus.AWAITING_ACCOUNTING:
        raise CompletionActRuleViolation("Оформить платёж можно только после согласования акта")
    if act.payment_order_file_id or act.posting_number:
        raise CompletionActRuleViolation("Оплата по акту уже проведена")
    check_agreement_capacity(agreement, act.amount)
    if not is_elevated:
        from apps.hr import interface as hr
        if not hr.user_has_permission(actor_id, ACCOUNT_PAYMENT_PERMISSION):
            raise PermissionError("Требуется роль «Бухгалтер»")
    stored = media.store_file(data=data, filename=filename, mime=mime,
                              scope="generic", owner_id=actor_id)
    act.payment_order_file_id = str(stored["id"])
    act.posting_number = posting_number
    act.paid_by = actor_id
    act.paid_at = timezone.now()
    act.status = AdvancePaymentStatus.CLOSED
    act.save(update_fields=["payment_order_file_id", "posting_number", "paid_by",
                            "paid_at", "status", "updated_at"])
    return get_completion_act_or_404(act.pk)


def act_url(act: CompletionAct) -> str | None:
    return media.get_file_url(act.act_file_id) if act.act_file_id else None


def payment_order_url(act: CompletionAct) -> str | None:
    return media.get_file_url(act.payment_order_file_id) if act.payment_order_file_id else None
