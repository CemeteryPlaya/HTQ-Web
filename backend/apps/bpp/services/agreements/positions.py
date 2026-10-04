"""Остатки позиций заявки — CALC-005, CALC-006 (ТЗ §08, §23; B3.1–B3.3).

- **Остаток кол-во для договора и плана** (CALC-005): план − Σ кол-ва в
  договорах, которые держат позицию (кроме «Отклонён», «Расторгнут»,
  «Исполнен», «Заменён» и удалённых), − Σ кол-ва в действующих счетах без
  договора. Расторгнутый и исполненный договор позицию отпускает: его
  неосвоенный остаток возвращается в план (Q-D02), а освоенное учитывают его
  счета.
- **Остаток кол-во для счёта** (CALC-005): план − Σ кол-ва в действующих
  счетах (с договором и без).
- **Остаток суммы** (CALC-006): плановая сумма − Σ строк действующих счетов,
  не меньше нуля.

«Действующий» счёт — любой, кроме «Отменён», «Не к оплате» и «Заменён
альтернативой»: черновик держит позицию так же, как черновик договора.
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal

from django.db.models import Sum

from apps.bpp.models import (
    AgreementItem,
    AgreementStatus,
    InvoiceBasis,
    InvoiceLine,
    InvoiceStatus,
    PurchaseRequestItem,
)

ZERO = Decimal("0")

#: Договоры, которые держат позиции плана (ТЗ CALC-005).
HOLDING_STATUSES = (AgreementStatus.DRAFT, AgreementStatus.ON_REVIEW,
                    AgreementStatus.ACTIVE, AgreementStatus.REWORK)
#: Счета, которые не держат позиции (ТЗ CALC-005, CALC-006, CALC-009).
RELEASED_INVOICE_STATUSES = (InvoiceStatus.CANCELLED, InvoiceStatus.NOT_PAYABLE,
                             InvoiceStatus.REPLACED)


def qty_in_agreements(item_ids: Iterable, *, exclude_agreement_id=None,
                      statuses=HOLDING_STATUSES) -> dict[str, Decimal]:
    rows = AgreementItem.objects.filter(request_item_id__in=list(item_ids),
                                        agreement__status__in=statuses)
    if exclude_agreement_id is not None:
        rows = rows.exclude(agreement_id=exclude_agreement_id)
    return {str(row["request_item_id"]): row["total"] for row in
            rows.values("request_item_id").annotate(total=Sum("qty"))}


def _invoice_lines(item_ids, exclude_invoice_id=None):
    rows = (InvoiceLine.objects.filter(request_item_id__in=list(item_ids))
            .exclude(invoice__status__in=RELEASED_INVOICE_STATUSES))
    if exclude_invoice_id is not None:
        rows = rows.exclude(invoice_id=exclude_invoice_id)
    return rows


def _sum_by_item(rows, field: str) -> dict[str, Decimal]:
    return {str(row["request_item_id"]): row["total"] for row in
            rows.values("request_item_id").annotate(total=Sum(field))}


def remaining(items: Iterable[PurchaseRequestItem], *, exclude_agreement_id=None,
              exclude_invoice_id=None) -> dict[str, dict]:
    """``{item_id: {qty_in_agreements, qty_in_invoices, qty_left,
    qty_left_for_invoice, amount_in_invoices, amount_left}}``.

    ``qty_left`` — для договора и плана, ``qty_left_for_invoice`` — для счёта;
    ``exclude_*`` — документ, который сверяют с остатком (он сам остаток не ест).
    """
    items = list(items)
    ids = [str(item.pk) for item in items]
    in_agreements = qty_in_agreements(ids, exclude_agreement_id=exclude_agreement_id)
    lines = _invoice_lines(ids, exclude_invoice_id)
    qty_all = _sum_by_item(lines, "qty")
    qty_no_contract = _sum_by_item(lines.filter(invoice__basis=InvoiceBasis.NO_CONTRACT), "qty")
    invoiced = _sum_by_item(lines, "amount")
    out = {}
    for item in items:
        key = str(item.pk)
        qty_agr = in_agreements.get(key, ZERO)
        qty_inv = qty_all.get(key, ZERO)
        amount_inv = invoiced.get(key, ZERO)
        out[key] = {
            "qty_in_agreements": qty_agr,
            "qty_in_invoices": qty_inv,
            "qty_left": max(item.qty - qty_agr - qty_no_contract.get(key, ZERO), ZERO),
            "qty_left_for_invoice": max(item.qty - qty_inv, ZERO),
            "amount_in_invoices": amount_inv,
            "amount_left": max(item.amount - amount_inv, ZERO),
        }
    return out


def on_review_item_ids(item_ids: Iterable) -> set[str]:
    """Позиции в договоре «На согласовании» — метка плана (ТЗ §8.3 п.3)."""
    return {str(pk) for pk in AgreementItem.objects.filter(
        request_item_id__in=list(item_ids), agreement__status=AgreementStatus.ON_REVIEW,
    ).values_list("request_item_id", flat=True)}
