"""Отметки оплаты бухгалтера и закрывающие документы (ТЗ §10.2, §10.4, §15.4;
D-11, D-13; задача B3.2).

- **Оплата** — BR-050, BR-052: сумма отметки ≤ неоплаченного остатка, под
  блокировкой счёта. Σ < суммы → «Оплачено частично», = суммы → «Оплачено».
  Частичная оплата и транши — несколько отметок (Q-B24).
- **Отмена отметки** — БУХ или ФД, пока банк её не подтвердил:
  ``paid_bank_amount`` ведёт сверка A4.2, до неё он всегда 0.
- **Закрывающие документы — только после оплаты** (D-13): БУХ запрашивает
  (ТМЦ → накладная, работы и услуги → АВР по умолчанию, §10.3 п.6) → «Ждёт
  закрывающих» → автор вкладывает → «Документы предоставлены» → БУХ
  принимает («Закрыт») или возвращает («Ждёт закрывающих»).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.bpp.models import Invoice, InvoiceBasis, InvoiceStatus, PaymentMark
from apps.bpp.services.actor import Actor
from apps.bpp.services.alternatives import kpi
from apps.bpp.services.core import audit
from apps.bpp.services.core import files as core_files
from apps.bpp.services.counterparties import lookup as counterparties
from apps.bpp.services.money import fmt, money
from htqweb.errors import DomainError

from . import invoices as service

DOC_TYPES = {"avr": "АВР", "waybill": "Накладная", "vat_invoice": "Счёт-фактура"}
#: Тип файла в ``apps.files`` у каждого закрывающего документа (ТЗ §21;
#: владелец ``bpp.invoice`` — ``services/invoices/file_owner.py``).
DOC_FILE_TYPES = {"avr": "act", "waybill": "waybill", "vat_invoice": "vat_invoice"}


def missing_docs(inv: Invoice, wanted: list[str]) -> list[str]:
    """Запрошенные закрывающие, по которым не вложено ни одного файла (ТЗ
    §10.2: «для каждого запрошенного типа ≥1 файл»)."""
    return [key for key in wanted if core_files.count_files(inv, DOC_FILE_TYPES[key]) == 0]


def paid_total(inv: Invoice) -> Decimal:
    return money(inv.payments.filter(cancelled_at__isnull=True)
                 .aggregate(total=Sum("amount"))["total"] or 0)


def _require_buh(actor: Actor, action: str) -> None:
    if not actor.can("bpp.invoices.payment", "edit"):
        raise service._deny(f"«{action}» — действие бухгалтера.")


def _status_by_paid(inv: Invoice, paid: Decimal) -> str:
    if paid <= 0:
        return InvoiceStatus.TO_PAY
    return InvoiceStatus.PAID if paid >= inv.amount else InvoiceStatus.PARTIALLY_PAID


@transaction.atomic
def mark_paid(actor: Actor, invoice_id, *, pay_date: date, amount, pp_number: str = "",
              rate=None) -> Invoice:
    """«Оплачено» (BR-050, BR-052). Первая полная оплата — удачный документ
    контрагента счёта без договора (метка «Проверенный», A2.3)."""
    _require_buh(actor, "Оплачено")
    inv = service.lock(invoice_id)
    service.require_status(inv, (InvoiceStatus.TO_PAY, InvoiceStatus.PARTIALLY_PAID),
                           "отметить оплату по")
    amount = money(amount)
    if amount <= 0:
        raise DomainError("E-VAL-01", "Сумма оплаты — больше нуля.",
                          fields=[{"field": "amount", "message": "> 0"}])
    if pay_date > timezone.localdate():
        raise DomainError("E-VAL-01", "Дата оплаты — не позже сегодняшней.",
                          fields=[{"field": "pay_date", "message": "≤ сегодня"}])
    paid = paid_total(inv)
    unpaid = inv.amount - paid
    if amount > unpaid:
        raise DomainError(
            "BR-052", f"Сумма оплаты {fmt(amount, inv.currency_code)} больше неоплаченного "
                      f"остатка счёта {inv.number} ({fmt(unpaid, inv.currency_code)}).",
            fields=[{"field": "amount", "message": "Больше неоплаченного остатка",
                     "unpaid": str(unpaid)}])
    PaymentMark.objects.create(invoice=inv, pay_date=pay_date, amount=amount,
                               pp_number=(pp_number or "").strip()[:50],
                               rate=Decimal(str(rate)) if rate is not None else None,
                               marked_by_id=actor.user_id, created_by=actor.user_id,
                               updated_by=actor.user_id)
    before = inv.status
    inv.status = _status_by_paid(inv, paid + amount)
    service.touch(inv, actor.user_id, "status")
    audit.record(inv, "payment_marked", actor_id=actor.user_id,
                 changes={"pay_date": pay_date.isoformat(), "amount": str(amount),
                          "pp_number": pp_number, "status": [before, inv.status]})
    if (inv.status == InvoiceStatus.PAID and inv.basis == InvoiceBasis.NO_CONTRACT
            and inv.counterparty_id):
        counterparties.record_success(inv.counterparty_id)
    kpi.sync_for_document("invoice", inv.pk)  # KPI снабжения нового счёта (A5.2)
    return inv


@transaction.atomic
def unmark(actor: Actor, invoice_id, mark_id, *, comment: str) -> Invoice:
    """«Отменить отметку оплаты» — БУХ или ФД, пока банк не подтвердил оплату."""
    if not (actor.can("bpp.invoices.payment", "edit")
            or actor.can("bpp.invoices.decision", "edit")):
        raise service._deny("Отменяет отметку оплаты бухгалтер или финансовый директор.")
    comment = service.comment_of(comment)
    inv = service.lock(invoice_id)
    service.require_status(inv, (InvoiceStatus.PARTIALLY_PAID, InvoiceStatus.PAID),
                           "отменить отметку оплаты по")
    if inv.paid_bank_amount > 0:
        raise DomainError(
            "E-STS-01", f"Нельзя отменить отметку: оплата по счёту {inv.number} уже "
                        f"подтверждена выпиской банка. Сначала отмените сопоставление строки "
                        f"выписки.", status=409)
    mark = inv.payments.filter(pk=mark_id, cancelled_at__isnull=True).first()
    if mark is None:
        raise DomainError("E-NOT-FOUND", "Отметка оплаты не найдена.", status=404)
    mark.cancelled_at, mark.cancelled_by_id, mark.cancel_comment = (timezone.now(),
                                                                    actor.user_id, comment)
    mark.save(update_fields=["cancelled_at", "cancelled_by_id", "cancel_comment",
                             "updated_at"])
    inv.status = _status_by_paid(inv, paid_total(inv))
    service.touch(inv, actor.user_id, "status")
    audit.record(inv, "payment_unmarked", actor_id=actor.user_id, comment=comment,
                 changes={"amount": str(mark.amount), "pay_date": mark.pay_date.isoformat()})
    kpi.sync_for_document("invoice", inv.pk)  # снятая отметка подтверждённый KPI не откатывает
    return inv


# ── закрывающие документы (D-13) ────────────────────────────────────────

def default_docs(inv: Invoice) -> dict[str, bool]:
    """ТМЦ → накладная, работы и услуги → АВР (ТЗ §10.3 п.6)."""
    return {"avr": inv.purchase_type == "works", "waybill": inv.purchase_type == "goods",
            "vat_invoice": False}


@transaction.atomic
def request_docs(actor: Actor, invoice_id, *, docs: dict[str, bool] | None = None,
                 comment: str = "") -> Invoice:
    _require_buh(actor, "Запросить документы")
    inv = service.lock(invoice_id)
    service.require_status(inv, (InvoiceStatus.PAID,), "запросить документы по")
    wanted = {key: bool((docs or default_docs(inv)).get(key)) for key in DOC_TYPES}
    if not any(wanted.values()):
        raise DomainError("E-VAL-01", "Отметьте хотя бы один документ: АВР, накладная или "
                                      "счёт-фактура.",
                          fields=[{"field": "docs", "message": "≥ 1 документ"}])
    inv.docs_required, inv.docs_requested_at = wanted, timezone.now()
    inv.docs_comment, inv.status = (comment or "").strip(), InvoiceStatus.AWAITING_DOCS
    service.touch(inv, actor.user_id, "docs_required", "docs_requested_at", "docs_comment",
                  "status")
    audit.record(inv, "docs_requested", actor_id=actor.user_id, comment=inv.docs_comment,
                 changes={"docs": [DOC_TYPES[k] for k, v in wanted.items() if v]})
    return inv


@transaction.atomic
def submit_docs(actor: Actor, invoice_id) -> Invoice:
    """«Документы вложены» — автор; ФД — от имени автора при его отсутствии
    (``bpp.invoices.closing_docs``)."""
    inv = service.lock(invoice_id)
    if inv.author_id != actor.user_id and not actor.can("bpp.invoices.closing_docs", "edit"):
        raise service._deny(f"Документы по счёту {inv.number} вкладывает автор счёта.")
    service.require_status(inv, (InvoiceStatus.AWAITING_DOCS,), "отправить документы по")
    wanted = [key for key, need in (inv.docs_required or {}).items() if need]
    missing = missing_docs(inv, wanted)
    if missing:
        raise DomainError(
            "E-INV-04", f"Не вложены запрошенные документы: "
                        f"{', '.join(DOC_TYPES[key] for key in missing)}. Вложите файлы и "
                        f"повторите.", fields=[{"field": "docs", "message": "Нет файлов"}])
    inv.status = InvoiceStatus.DOCS_PROVIDED
    service.touch(inv, actor.user_id, "status")
    audit.record(inv, "docs_submitted", actor_id=actor.user_id,
                 changes={"on_behalf": inv.author_id != actor.user_id})
    return inv


@transaction.atomic
def accept_docs(actor: Actor, invoice_id) -> Invoice:
    _require_buh(actor, "Принять документы")
    inv = service.lock(invoice_id)
    service.require_status(inv, (InvoiceStatus.DOCS_PROVIDED,), "принять документы по")
    inv.status = InvoiceStatus.CLOSED
    service.touch(inv, actor.user_id, "status")
    audit.record(inv, "docs_accepted", actor_id=actor.user_id)
    return inv


@transaction.atomic
def return_docs(actor: Actor, invoice_id, *, comment: str) -> Invoice:
    _require_buh(actor, "Вернуть документы")
    comment = service.comment_of(comment)
    inv = service.lock(invoice_id)
    service.require_status(inv, (InvoiceStatus.DOCS_PROVIDED,), "вернуть документы по")
    inv.status, inv.docs_comment = InvoiceStatus.AWAITING_DOCS, comment
    service.touch(inv, actor.user_id, "status", "docs_comment")
    audit.record(inv, "docs_returned", actor_id=actor.user_id, comment=comment)
    return inv


def closing_docs_pending_for_user(user_id: int) -> list[dict]:
    """Счета автора в «Ждёт закрывающих документов» — контракт §2.6 для
    ежедневной сводки (A3.2, D-13): ``[{invoice_id, number, title, url, since}]``."""
    today = timezone.localdate()
    out = []
    for inv in (Invoice.objects.filter(author_id=user_id, status=InvoiceStatus.AWAITING_DOCS)
                .order_by("docs_requested_at")):
        since = inv.docs_requested_at
        days = (today - timezone.localtime(since).date()).days if since else 0
        out.append({"invoice_id": str(inv.pk), "number": inv.number,
                    "title": f"{inv.number} — ждёт закрывающих {days} дн.",
                    "url": f"/bpp/invoices/{inv.pk}", "since": since, "days": days})
    return out
