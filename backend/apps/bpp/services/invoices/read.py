"""Чтение счёта: карточка F-05, реестр L-06 с вкладками, значок дробления,
выгрузка очереди к оплате, поиск по номеру (ТЗ §10, §19; D-17; B3.2).

Вкладки реестра (§10.5): «Все», «На решение ФД», «К оплате», «Ждут
закрывающих», «Документы предоставлены», «Оплачено, банк не подтвердил»,
«Расхождения с банком». Итоговая строка — Σ сумм и Σ оплачено по банку по
всей выборке.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.db.models import Q, Sum
from django.utils import timezone

from apps.bpp.models import Invoice, InvoiceBasis, InvoiceStatus, ReconStatus
from apps.bpp.services import calc
from apps.bpp.services.actor import Actor
from apps.bpp.services.agreements import agreements as agreement_service
from apps.bpp.services.agreements import positions
from apps.bpp.services.counterparties import lookup as counterparties
from apps.project import interface as projects
from apps.refdata import interface as refdata
from apps.signoff import interface as signoff
from apps.users import interface as users
from htqweb.errors import DomainError

from . import invoices as service
from . import payments

SUBJECT = Invoice.SIGNOFF_SUBJECT_TYPE
ZERO = Decimal("0.00")
#: Окно «дробления» для счетов без договора одному контрагенту (D-17).
SPLIT_WINDOW_DAYS = 30

TABS = {
    "all": None,
    "fd": Q(status=InvoiceStatus.UNDER_REVIEW),
    "to_pay": Q(status__in=[InvoiceStatus.TO_PAY, InvoiceStatus.PARTIALLY_PAID]),
    "awaiting_docs": Q(status=InvoiceStatus.AWAITING_DOCS),
    "docs_provided": Q(status=InvoiceStatus.DOCS_PROVIDED),
    "bank_unconfirmed": Q(status__in=[InvoiceStatus.PAID, InvoiceStatus.AWAITING_DOCS,
                                      InvoiceStatus.DOCS_PROVIDED, InvoiceStatus.CLOSED],
                          recon_status=ReconStatus.NO_DATA),
    "bank_mismatch": Q(recon_status__in=[ReconStatus.PARTIAL, ReconStatus.OVERPAID])
    & ~Q(status=InvoiceStatus.PARTIALLY_PAID),
}


def _names(ids) -> dict[int, str]:
    ids = [uid for uid in set(ids) if uid]
    return {row["id"]: row["full_name"] for row in users.get_users_brief(ids)} if ids else {}


# ── дробление (D-17, BR-047) ────────────────────────────────────────────

def split_flags(invoices: list[Invoice]) -> set[str]:
    """Счета без договора, у которых Σ счетов без договора тому же контрагенту
    по той же заявке **или** за 30 дней больше порога 1000 МРП — значок
    «Возможное дробление» для ФД. Запрета нет."""
    flagged: set[str] = set()
    for inv in invoices:
        if inv.basis != InvoiceBasis.NO_CONTRACT or not inv.counterparty_id or not inv.ext_date:
            continue
        try:
            limit = calc.threshold(inv.ext_date)
        except DomainError:
            continue
        base = (Invoice.objects.filter(basis=InvoiceBasis.NO_CONTRACT,
                                       counterparty_id=inv.counterparty_id)
                .exclude(status__in=[InvoiceStatus.DRAFT, *positions.RELEASED_INVOICE_STATUSES]))
        window = base.filter(ext_date__gte=inv.ext_date - timedelta(days=SPLIT_WINDOW_DAYS),
                             ext_date__lte=inv.ext_date)
        requests = set(inv.lines.values_list("request_item__request_id", flat=True))
        same_request = base.filter(lines__request_item__request_id__in=requests).distinct()
        for rows in (window, same_request):
            total = rows.aggregate(total=Sum("amount_kzt"))["total"] or ZERO
            if total > limit:
                flagged.add(str(inv.pk))
                break
    return flagged


# ── карточка ────────────────────────────────────────────────────────────

def card(actor: Actor, inv: Invoice, *, vat_warning: str | None = None) -> dict:
    project = projects.project_brief([str(inv.project_id)]).get(str(inv.project_id)) or {}
    article = refdata.article_brief([str(inv.article_id)]).get(str(inv.article_id)) or {}
    lines = list(inv.lines.select_related("request_item", "request_item__request")
                 .order_by("request_item__sys_number"))
    left = positions.remaining([line.request_item for line in lines], exclude_invoice_id=inv.pk)
    cp = counterparties.brief([inv.counterparty_id]).get(str(inv.counterparty_id)) \
        if inv.counterparty_id else None
    names = _names([inv.author_id, *[p.marked_by_id for p in inv.payments.all()]])
    holders = signoff.current_holders(SUBJECT, [str(inv.pk)]).get(str(inv.pk))
    agr = inv.agreement
    threshold = None
    if inv.basis == InvoiceBasis.NO_CONTRACT and inv.ext_date:
        try:
            threshold = calc.threshold(inv.ext_date)
        except DomainError:
            threshold = None
    paid = payments.paid_total(inv)
    days_waiting = None
    if inv.status == InvoiceStatus.AWAITING_DOCS and inv.docs_requested_at:
        days_waiting = (timezone.localdate()
                        - timezone.localtime(inv.docs_requested_at).date()).days
    return {
        "id": str(inv.pk), "number": inv.number, "status": inv.status,
        "approval_state": inv.approval_state, "version": inv.version,
        "author_id": inv.author_id, "author_name": names.get(inv.author_id),
        "created_at": inv.created_at, "basis": inv.basis,
        "initiator_role": inv.initiator_role,
        "agreement": None if agr is None else {
            "id": str(agr.pk), "number": agr.number, "ext_number": agr.ext_number,
            "ext_date": agr.ext_date, "is_open": agr.is_open, "status": agr.status,
            "effective_amount": agreement_service.effective_amount(agr),
            "remaining": _agreement_remaining(agr, inv)},
        "project": {"id": str(inv.project_id), "code": project.get("code"),
                    "name": project.get("name")},
        "article": {"id": str(inv.article_id), "code": article.get("code"),
                    "name": article.get("name")},
        "counterparty": cp, "counterparty_confirmed": inv.counterparty_confirmed,
        "ext_number": inv.ext_number, "ext_date": inv.ext_date,
        "amount": inv.amount, "currency_code": inv.currency_code,
        "rate": inv.rate, "rate_source": inv.rate_source, "amount_kzt": inv.amount_kzt,
        "threshold": threshold,
        "over_threshold": bool(threshold is not None and inv.amount_kzt is not None
                               and inv.amount_kzt > threshold),
        "with_vat": inv.with_vat, "vat_rate": inv.vat_rate, "vat_source": inv.vat_source,
        "vat_amount": inv.vat_amount, "vat_warning": vat_warning,
        "purchase_type": inv.purchase_type, "is_advance": inv.is_advance,
        "due_date": inv.due_date, "planned_pay_date": inv.planned_pay_date,
        "fd_decided_at": inv.fd_decided_at,
        "status_comment": inv.status_comment,
        "rework_comment": inv.rework_comment if inv.status == InvoiceStatus.RETURNED else "",
        "author_comment": inv.author_comment,
        "docs_required": inv.docs_required or {}, "docs_requested_at": inv.docs_requested_at,
        "docs_comment": inv.docs_comment, "days_waiting_docs": days_waiting,
        "recon_status": inv.recon_status, "paid_bank_amount": inv.paid_bank_amount,
        "paid_amount": paid, "unpaid_amount": inv.amount - paid,
        "payments": [{"id": str(p.pk), "pay_date": p.pay_date, "amount": p.amount,
                      "pp_number": p.pp_number, "rate": p.rate,
                      "marked_by_name": names.get(p.marked_by_id),
                      "cancelled_at": p.cancelled_at, "cancel_comment": p.cancel_comment}
                     for p in inv.payments.order_by("created_at")],
        "possible_split": str(inv.pk) in split_flags([inv]),
        "lines": [{
            "id": str(line.pk), "request_item_id": str(line.request_item_id),
            "sys_number": line.request_item.sys_number, "name": line.request_item.name,
            "request_id": str(line.request_item.request_id),
            "request_number": line.request_item.request.number,
            "qty": line.qty, "amount": line.amount,
            "plan_amount": line.request_item.amount,
            "qty_available": service.qty_available(left[str(line.request_item_id)], inv.basis),
            "amount_available": left[str(line.request_item_id)]["amount_left"],
        } for line in lines],
        "current_holders": holders,
        "allowed_actions": service.allowed_actions(actor, inv),
    }


def _agreement_remaining(agr, inv: Invoice) -> Decimal | None:
    total = agreement_service.effective_amount(agr)
    if total is None:
        return None
    invoiced = service.invoiced_by_agreement([str(agr.pk)], exclude_invoice_id=inv.pk)
    return total - invoiced.get(str(agr.pk), ZERO)


# ── реестр ──────────────────────────────────────────────────────────────

def _visible(actor: Actor, filters: dict):
    rows = Invoice.objects.filter(is_migrated=False)
    if not service.sees_all(actor):
        awaiting = [str(sid) for sid in signoff.list_awaiting_subject_ids(actor.user_id, SUBJECT)]
        rows = rows.filter(Q(author_id=actor.user_id) | Q(pk__in=awaiting))
    tab = TABS.get(filters.get("tab") or "all")
    if tab is not None:
        rows = rows.filter(tab)
    if filters.get("statuses"):
        rows = rows.filter(status__in=filters["statuses"])
    if filters.get("project_ids"):
        rows = rows.filter(project_id__in=filters["project_ids"])
    if filters.get("article_ids"):
        rows = rows.filter(article_id__in=filters["article_ids"])
    if filters.get("counterparty_id"):
        rows = rows.filter(counterparty_id=filters["counterparty_id"])
    if filters.get("basis"):
        rows = rows.filter(basis=filters["basis"])
    if filters.get("agreement_id"):
        rows = rows.filter(agreement_id=filters["agreement_id"])
    if filters.get("date_from"):
        rows = rows.filter(ext_date__gte=filters["date_from"])
    if filters.get("date_to"):
        rows = rows.filter(ext_date__lte=filters["date_to"])
    if filters.get("search"):
        text = filters["search"]
        rows = rows.filter(Q(number__icontains=text) | Q(ext_number__icontains=text)
                           | Q(counterparty__reg_number__icontains=text))
    order = ("due_date", "created_at") if filters.get("tab") in ("fd", "to_pay") \
        else ("-created_at",)
    return rows.select_related("counterparty", "agreement").order_by(*order)


def _rows(chunk: list[Invoice]) -> list[dict]:
    project_map = projects.project_brief(list({str(i.project_id) for i in chunk}))
    article_map = refdata.article_brief(list({str(i.article_id) for i in chunk}))
    names = _names([i.author_id for i in chunk])
    holders = signoff.current_holders(SUBJECT, [str(i.pk) for i in chunk]) if chunk else {}
    split = split_flags(chunk)
    today = timezone.localdate()
    out = []
    for inv in chunk:
        due = inv.planned_pay_date or inv.due_date
        out.append({
            "id": str(inv.pk), "number": inv.number, "status": inv.status,
            "created_at": inv.created_at, "author_name": names.get(inv.author_id),
            "basis": inv.basis,
            "agreement_number": inv.agreement.number if inv.agreement_id else None,
            "project_code": project_map.get(str(inv.project_id), {}).get("code"),
            "article_name": article_map.get(str(inv.article_id), {}).get("name"),
            "counterparty_id": str(inv.counterparty_id) if inv.counterparty_id else None,
            "counterparty_name": (counterparties.display_name(inv.counterparty)
                                  if inv.counterparty_id else None),
            "counterparty_reg_number": inv.counterparty.reg_number if inv.counterparty_id else None,
            "counterparty_blocked": bool(inv.counterparty_id
                                         and inv.counterparty.status == "blocked"),
            "ext_number": inv.ext_number, "ext_date": inv.ext_date,
            "amount": inv.amount, "currency_code": inv.currency_code,
            "amount_kzt": inv.amount_kzt, "due_date": inv.due_date,
            "planned_pay_date": inv.planned_pay_date,
            "overdue": bool(due and due < today and inv.status in (
                InvoiceStatus.UNDER_REVIEW, InvoiceStatus.TO_PAY, InvoiceStatus.PARTIALLY_PAID)),
            "docs_required": inv.docs_required or {},
            "days_waiting_docs": ((today - timezone.localtime(inv.docs_requested_at).date()).days
                                  if inv.status == InvoiceStatus.AWAITING_DOCS
                                  and inv.docs_requested_at else None),
            "recon_status": inv.recon_status, "paid_bank_amount": inv.paid_bank_amount,
            "possible_split": str(inv.pk) in split,
            "current_holders": holders.get(str(inv.pk)),
        })
    return out


def registry(actor: Actor, *, filters: dict | None = None, page: int = 1,
             page_size: int = 50) -> dict:
    rows = _visible(actor, filters or {})
    total = rows.count()
    sums = rows.aggregate(amount=Sum("amount_kzt"), paid_bank=Sum("paid_bank_amount"))
    page_size = page_size if page_size in (25, 50, 100) else 50
    chunk = list(rows[(page - 1) * page_size: page * page_size])
    return {"items": _rows(chunk), "total": total, "page": page, "page_size": page_size,
            "totals": {"amount_kzt": sums["amount"] or ZERO,
                       "paid_bank_amount": sums["paid_bank"] or ZERO}}


# ── выгрузки ────────────────────────────────────────────────────────────

EXPORT_REBUILD_PATH = "apps.bpp.services.invoices.read.export_rows"
QUEUE_REBUILD_PATH = "apps.bpp.services.invoices.read.queue_rows"
_EXPORT_CHUNK = 500


def export_count(*, user_id: int, company: str | None, is_superuser: bool = False,
                 filters: dict) -> int:
    actor = Actor.for_user(user_id, company=company, is_superuser=is_superuser)
    return _visible(actor, filters).count()


def export_rows(*, user_id: int, company: str | None, is_superuser: bool = False,
                filters: dict):
    actor = Actor.for_user(user_id, company=company, is_superuser=is_superuser)
    labels = dict(InvoiceStatus.choices)
    chunk: list[Invoice] = []
    for inv in _visible(actor, filters).iterator(chunk_size=_EXPORT_CHUNK):
        chunk.append(inv)
        if len(chunk) == _EXPORT_CHUNK:
            yield from _export_chunk(chunk, labels)
            chunk = []
    yield from _export_chunk(chunk, labels)


def _export_chunk(chunk, labels):
    for row in _rows(chunk):
        yield {**row, "status": labels.get(row["status"], row["status"]),
               "basis": dict(InvoiceBasis.choices).get(row["basis"], row["basis"])}


def payment_purpose(inv: Invoice) -> str:
    """Назначение платежа (ТЗ §10.5): «Оплата по счёту № <номер контрагента>
    от <дата>, СЧ-…» — системный номер ищет сверка (BR-070)."""
    when = f" от {inv.ext_date:%d.%m.%Y}" if inv.ext_date else ""
    return f"Оплата по счёту № {inv.ext_number}{when}, {inv.number}"


def queue_count(*, user_id: int, company: str | None, is_superuser: bool = False) -> int:
    actor = Actor.for_user(user_id, company=company, is_superuser=is_superuser)
    return _visible(actor, {"tab": "to_pay"}).count()


def queue_rows(*, user_id: int, company: str | None, is_superuser: bool = False):
    """«Экспорт очереди к оплате» (ТЗ §10.5): номер, контрагент, БИН, IBAN,
    сумма к оплате, назначение платежа."""
    actor = Actor.for_user(user_id, company=company, is_superuser=is_superuser)
    for inv in _visible(actor, {"tab": "to_pay"}).iterator(chunk_size=_EXPORT_CHUNK):
        account = (inv.counterparty.bank_accounts.filter(is_active=True).order_by("-is_primary")
                   .first() if inv.counterparty_id else None)
        yield {
            "number": inv.number,
            "counterparty": counterparties.display_name(inv.counterparty)
            if inv.counterparty_id else "",
            "reg_number": inv.counterparty.reg_number if inv.counterparty_id else "",
            "iban": getattr(account, "iban", "") or "",
            "amount": inv.amount - payments.paid_total(inv),
            "currency_code": inv.currency_code,
            "planned_pay_date": inv.planned_pay_date or inv.due_date,
            "purpose": payment_purpose(inv),
        }


# ── для сверки (A4.2) ───────────────────────────────────────────────────

def find_by_number(number: str) -> dict | None:
    """``СЧ-ГГГГ-NNNNNN`` → счёт для сверки выписки (контракт §2.6, A4.2)."""
    inv = (Invoice.objects.select_related("counterparty")
           .filter(number=(number or "").strip().upper()).first())
    if inv is None:
        return None
    return {"id": str(inv.pk), "number": inv.number, "status": inv.status,
            "amount": inv.amount, "currency_code": inv.currency_code,
            "counterparty_reg_number": inv.counterparty.reg_number if inv.counterparty_id else "",
            "paid_bank_amount": inv.paid_bank_amount, "recon_status": inv.recon_status}
