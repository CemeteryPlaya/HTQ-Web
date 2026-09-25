"""Товарные накладные: загрузка накладной, согласование и проведение оплаты."""

from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.http import Http404
from django.utils import timezone

from apps.contracts.models import (
    Administrator, AdvancePayment, AdvancePaymentStatus, Agreement, AgreementStatus,
    CompletionAct, ContractPayment, GoodsInvoice,
)
from apps.contracts.services import budget_calc
from apps.media_files import interface as media
from apps.signoff import interface as signoff


# Накладная проводится тем же бухгалтером, что и оплата по договору/акту:
# отдельная роль не нужна, поскольку жизненный цикл и финансовая операция
# одинаковы (см. completion_act_service).
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


class GoodsInvoiceRuleViolation(Exception):
    """Нарушено правило жизненного цикла товарной накладной."""


def get_goods_invoice_or_404(invoice_id: int, *, lock: bool = False) -> GoodsInvoice:
    query = GoodsInvoice.objects.select_related(*_RELATED)
    if lock:
        query = query.select_for_update()
    invoice = query.filter(pk=invoice_id).first()
    if invoice is None:
        raise Http404("Товарная накладная не найдена")
    return invoice


def _eligible_agreement(agreement_id: int) -> Agreement:
    agreement = (Agreement.objects.select_for_update()
                 .select_related("counterparty", "budget_line__budget")
                 .filter(pk=agreement_id).first())
    if agreement is None:
        raise Http404("Договор не найден")
    if not agreement.is_approved or agreement.status not in (
        AgreementStatus.APPROVED, AgreementStatus.SIGNED,
    ):
        raise GoodsInvoiceRuleViolation(
            "Накладную можно оформить только по действующему согласованному договору"
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
    invoices = (GoodsInvoice.objects
               .filter(agreement_id=agreement_id, status=AdvancePaymentStatus.CLOSED)
               .aggregate(total=Sum("amount"))["total"] or ZERO)
    return advance + payments + acts + invoices


def check_agreement_capacity(agreement: Agreement, amount) -> None:
    # Открытый договор суммы не имеет — сравнивать оплату не с чем. Без этой
    # оговорки его ``amount = 0`` запрещал бы любую оплату по нему.
    if not agreement.has_fixed_amount:
        return
    remaining = agreement.amount - paid_amount_for_agreement(agreement.pk)
    if amount > remaining:
        raise GoodsInvoiceRuleViolation(
            f"Сумма накладной {amount} превышает остаток договора {agreement.number}: "
            f"доступно {remaining}"
        )


def serialize_goods_invoice(invoice: GoodsInvoice, *, with_budget: bool = False) -> dict:
    """``with_budget`` — см. ``advance_payment_service.serialize_advance_payment``."""
    agreement = invoice.agreement
    return {
        "id": invoice.pk,
        "administrator_id": invoice.administrator_id,
        "administrator_name": invoice.administrator.display_name,
        "agreement_id": agreement.pk,
        "agreement_number": agreement.number,
        "agreement_name": agreement.name,
        "counterparty_name": agreement.counterparty.name,
        "amount": invoice.amount,
        "currency": agreement.currency,
        "waybill_file_id": invoice.waybill_file_id,
        "status": invoice.status,
        "approval_state": invoice.approval_state,
        "payment_order_file_id": invoice.payment_order_file_id,
        "posting_number": invoice.posting_number,
        "paid_by": invoice.paid_by,
        "paid_at": invoice.paid_at,
        "created_by": invoice.created_by,
        "created_at": invoice.created_at,
        "updated_at": invoice.updated_at,
        "budget_overrun": budget_calc.open_payment_overrun(invoice) if with_budget else None,
    }


def list_goods_invoices(*, administrator_id: int | None = None,
                        agreement_id: int | None = None,
                        awaiting_payment: bool | None = None):
    query = GoodsInvoice.objects.select_related(*_RELATED)
    if administrator_id is not None:
        query = query.filter(administrator_id=administrator_id)
    if agreement_id is not None:
        query = query.filter(agreement_id=agreement_id)
    if awaiting_payment is True:
        query = query.filter(status=AdvancePaymentStatus.AWAITING_ACCOUNTING)
    return list(query)


@transaction.atomic
def create_goods_invoice(*, administrator_id: int, agreement_id: int, amount,
                         waybill_data: bytes, waybill_filename: str, waybill_mime: str,
                         created_by: int | None = None) -> GoodsInvoice:
    agreement = _eligible_agreement(agreement_id)
    administrator = Administrator.objects.filter(pk=administrator_id, is_active=True).first()
    if administrator is None:
        raise GoodsInvoiceRuleViolation("Администратор не найден или отключён")
    if agreement.budget_line.budget.administrator_id != administrator.pk:
        raise GoodsInvoiceRuleViolation("Выбранный администратор не связан с договором")
    check_agreement_capacity(agreement, amount)
    stored = media.store_file(data=waybill_data, filename=waybill_filename, mime=waybill_mime,
                              scope="generic", owner_id=created_by)
    return GoodsInvoice.objects.create(
        administrator=administrator, agreement=agreement, amount=amount,
        waybill_file_id=str(stored["id"]), created_by=created_by,
    )


@transaction.atomic
def submit_for_approval(invoice_id: int, *, actor_id: int | None = None) -> dict:
    invoice = get_goods_invoice_or_404(invoice_id, lock=True)
    agreement = _eligible_agreement(invoice.agreement_id)
    if invoice.status != AdvancePaymentStatus.DRAFT:
        raise GoodsInvoiceRuleViolation("На согласование можно отправить только черновик накладной")
    check_agreement_capacity(agreement, invoice.amount)
    if invoice.approval_state not in signoff.ApprovalState.editable():
        invoice.assert_editable()
    return signoff.start_process(subject_type=GoodsInvoice.SIGNOFF_SUBJECT_TYPE,
                                 subject_id=invoice.pk, initiator_id=actor_id, enrich=True)


def change_status(invoice_id: int, new_status: str) -> GoodsInvoice:
    invoice = get_goods_invoice_or_404(invoice_id)
    if new_status not in AdvancePaymentStatus.values:
        raise GoodsInvoiceRuleViolation(f"Неизвестный статус накладной: {new_status}")
    if new_status == invoice.status:
        return invoice
    if new_status not in _ALLOWED_TRANSITIONS[invoice.status]:
        raise GoodsInvoiceRuleViolation("Переход статуса накладной не разрешён")
    invoice.status = new_status
    invoice.save(update_fields=["status", "updated_at"])
    return invoice


@transaction.atomic
def record_payment(invoice_id: int, *, posting_number: str, data: bytes,
                   filename: str, mime: str, actor_id: int,
                   is_elevated: bool = False) -> GoodsInvoice:
    invoice = get_goods_invoice_or_404(invoice_id, lock=True)
    agreement = _eligible_agreement(invoice.agreement_id)
    if not invoice.is_approved or invoice.status != AdvancePaymentStatus.AWAITING_ACCOUNTING:
        raise GoodsInvoiceRuleViolation("Оформить платёж можно только после согласования накладной")
    if invoice.payment_order_file_id or invoice.posting_number:
        raise GoodsInvoiceRuleViolation("Оплата по накладной уже проведена")
    check_agreement_capacity(agreement, invoice.amount)
    if not is_elevated:
        from apps.hr import interface as hr
        if not hr.user_has_permission(actor_id, ACCOUNT_PAYMENT_PERMISSION):
            raise PermissionError("Требуется роль «Бухгалтер»")
    stored = media.store_file(data=data, filename=filename, mime=mime,
                              scope="generic", owner_id=actor_id)
    invoice.payment_order_file_id = str(stored["id"])
    invoice.posting_number = posting_number
    invoice.paid_by = actor_id
    invoice.paid_at = timezone.now()
    invoice.status = AdvancePaymentStatus.CLOSED
    invoice.save(update_fields=["payment_order_file_id", "posting_number", "paid_by",
                                "paid_at", "status", "updated_at"])
    return get_goods_invoice_or_404(invoice.pk)


def waybill_url(invoice: GoodsInvoice) -> str | None:
    return media.get_file_url(invoice.waybill_file_id) if invoice.waybill_file_id else None


def payment_order_url(invoice: GoodsInvoice) -> str | None:
    return media.get_file_url(invoice.payment_order_file_id) if invoice.payment_order_file_id else None
