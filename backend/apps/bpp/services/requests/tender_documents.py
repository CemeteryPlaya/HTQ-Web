"""Пакет B-2: документы БЗО из тендера (тендер T5.3; спека этапа 5 tender, §3
T5.3; мастер-план tender §3.4, T-15, T-16, T-18, T-20).

- ``create_documents`` — черновики договоров и счетов по утверждённой ЗЗ
  ``source="tender"`` от имени закупщика (автора ЗЗ, T-20), по образцу
  выбора альтернативы (``selection/documents.py``). Идемпотентно по ключу
  передачи (``tender_key``, уникален в БД): повтор отдаёт уже созданное.
  План БЗО не участвует — позиции тендера в нём скрыты (T-07), это
  единственный путь документов на такие ЗЗ. Проверки остатков (BR-042) и
  бюджета (BR-034/BR-043) — штатно, при отправке документа закупщиком.
- Схемы оплаты (T-15): предоплата и аванс — счёт «аванс» (аванс — один счёт
  с частичными отметками БУХ, D-11); постоплата — «оплата после приёмки» и
  отсрочка в банковских днях (S5-12).
- ``documents_status`` — документы ЗЗ, оплаты по отметкам БУХ, запрос
  закрывающих, приёмка, замена альтернативой (T-18).
- ``set_acceptance`` — отметка «Товар принят, оригиналы переданы»; у счёта
  «после приёмки» — срок оплаты = приёмка + N банковских дней.
- ``attach_closing_docs`` — закрывающие из тендера по правилу D-13: только в
  «Ждёт закрывающих» и только запрошенного типа; повтор не дублирует.

Документ «из тендера» — со своим ключом передачи, счёт по договору из тендера
(договор передан тендером, счёт по нему оформлен в БЗО, ТЗ §9.4) или документ,
заменивший документ из тендера выбранной альтернативой (B5.1, T-18): поставку
по нему ведёт тендер, поэтому приёмку, закрывающие и смену статуса (слушатель —
с ключом исходного документа) он получает так же (``tender_key_of``).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import Sum

from apps.bpp.models import (
    Agreement,
    AlternativeOffer,
    Invoice,
    InvoiceStatus,
    PaymentMark,
    PurchaseRequest,
    RequestSource,
    RequestStatus,
    VatSource,
)
from apps.bpp.schemas.tender import (
    ClosingFileIn,
    DocumentRef,
    DocumentStatusOut,
    HandoverDocIn,
    ReplacedBy,
    TenderActor,
    TenderHandover,
)
from apps.bpp.services.core import audit
from apps.bpp.services.core import files as core_files
from apps.bpp.services.counterparties import lookup as counterparties
from apps.bpp.services.money import money
from apps.files import interface as files
from apps.refdata import interface as refdata
from htqweb.errors import DomainError

from .tender import _actor, _uuid

KP_TYPE = "alternative_offer"           # файл КП у документа (тот же код, что у B5.1)
POSTPAY_DEFAULT_DAYS = 14               # отсрочка схемы 3 по умолчанию (S5-12)
DOC_FILE_TYPES = {"avr": "act", "waybill": "waybill", "vat_invoice": "vat_invoice"}

#: Глубина цепочки «счёт → договор → заменённый альтернативой» — с запасом:
#: замена замены и счёт по договору-замене — уже три звена.
_KEY_DEPTH = 6


def tender_key_of(doc_type: str, doc, *, depth: int = 0) -> str:
    """Ключ передачи документа из тендера: свой; у счёта по договору — ключ
    договора; у документа, заменившего другой выбранной альтернативой, — ключ
    исходного. Не из тендера — пустая строка."""
    if doc is None or depth > _KEY_DEPTH:
        return ""
    if doc.tender_key:
        return doc.tender_key
    if doc_type == "invoice" and doc.agreement_id:
        key = tender_key_of("agreement", doc.agreement, depth=depth + 1)
        if key:
            return key
    offer = (AlternativeOffer.objects.filter(result_type=doc_type, result_id=doc.pk)
             .only("source_type", "source_id").first())
    if offer is None:
        return ""
    model = Invoice if offer.source_type == "invoice" else Agreement
    return tender_key_of(offer.source_type, model.objects.filter(pk=offer.source_id).first(),
                         depth=depth + 1)


def _tender_invoices(keys, *, lock: bool) -> list[Invoice]:
    rows = Invoice.objects.select_related("agreement").filter(pk__in=keys)
    if lock:
        rows = rows.select_for_update(of=("self",))
    return [inv for inv in rows if tender_key_of("invoice", inv)]


def _existing(key: str):
    inv = Invoice.objects.filter(tender_key=key).first()
    if inv is not None:
        return "invoice", inv
    agr = Agreement.objects.filter(tender_key=key).first()
    return ("agreement", agr) if agr is not None else (None, None)


def _ref(key: str, doc_type: str, doc) -> DocumentRef:
    return DocumentRef(key=key, doc_type=doc_type, doc_id=str(doc.pk), number=doc.number,
                       status=doc.status)


def _request(doc: HandoverDocIn, actor: TenderActor) -> PurchaseRequest:
    key = _uuid(doc.bpp_request_id)
    req = (PurchaseRequest.objects.select_for_update().filter(pk=key).first() if key else None)
    if req is None:
        raise DomainError("E-NOT-FOUND", "Заявка на закупку не найдена.", status=404)
    if req.source != RequestSource.TENDER:
        raise DomainError("E-STS-02", f"Заявка {req.number} — не из тендера: документы по ней "
                                      f"оформляются в БЗО.", status=409)
    if req.status != RequestStatus.APPROVED:
        raise DomainError("E-STS-01", f"Заявка {req.number} в статусе "
                                      f"«{req.get_status_display()}» — документы оформляют по "
                                      f"утверждённой.", status=409)
    if req.author_id != actor.user_id and not actor.is_superuser:
        raise DomainError("E-ACC-01", f"Документы по заявке {req.number} оформляет её автор.",
                          status=403)
    return req


def _rows(req: PurchaseRequest, doc: HandoverDocIn):
    by_id = {str(item.pk): item for item in req.items.all()}
    rows, quantities, amounts = [], {}, {}
    for index, line in enumerate(doc.lines):
        if line.bpp_request_item_id is None and len(by_id) == 1:
            item = next(iter(by_id.values()))       # доставка и СМР — одна позиция ЗЗ
        else:
            item = by_id.get(str(_uuid(line.bpp_request_item_id)))
        if item is None:
            raise DomainError("E-VAL-01", f"Позиция не из заявки {req.number}.",
                              fields=[{"field": f"lines[{index}].bpp_request_item_id",
                                       "message": "Позиция не из этой заявки"}])
        rows.append(item)
        quantities[str(item.pk)] = line.qty
        amounts[str(item.pk)] = money(line.amount)
    return rows, quantities, amounts


def _apply_common(doc, data: HandoverDocIn, counterparty, tender_number: str) -> None:
    doc.counterparty = counterparty
    doc.currency_code, doc.with_vat = data.currency_code, data.with_vat
    if data.with_vat and data.vat_rate is not None:
        doc.vat_rate, doc.vat_source = data.vat_rate, VatSource.MANUAL
    doc.source_tender, doc.tender_key = tender_number, data.key


def _create_one(actor: TenderActor, data: HandoverDocIn, tender_number: str):
    from apps.bpp.services.agreements import agreements as agreement_service
    from apps.bpp.services.invoices import invoices as invoice_service

    req = _request(data, actor)
    counterparty = counterparties.assert_usable(data.counterparty_id)
    rows, quantities, amounts = _rows(req, data)
    author = _actor(actor)
    if data.kind == "invoice":
        doc = invoice_service.new_invoice(author, rows=rows, agreement=None,
                                          quantities=quantities, amounts=amounts)
        _apply_common(doc, data, counterparty, tender_number)
        doc.is_advance = data.payment in ("prepay", "advance")
        doc.pay_after_receipt = data.payment == "postpay"
        doc.postpay_days = ((data.postpay_days or POSTPAY_DEFAULT_DAYS)
                            if data.payment == "postpay" else None)
        if doc.pay_after_receipt:
            doc.due_date = None             # срок — от приёмки (``set_acceptance``)
        invoice_service.recalc(doc)
    else:
        doc = agreement_service.new_agreement(
            author, rows=rows, project_id=req.project_id, article_id=req.article_id,
            kind=req.purchase_type, quantities=quantities, amounts=amounts)
        _apply_common(doc, data, counterparty, tender_number)
        agreement_service.recalc_vat(doc)
    doc.save()
    owner = core_files.owner_type_of(doc)
    for media_file_id in data.offer_media_file_ids:
        files.adopt_media_file(owner, doc.pk, file_type=KP_TYPE, media_file_id=media_file_id,
                               uploaded_by_id=actor.user_id)
    audit.record(doc, "created_from_tender", actor_id=actor.user_id,
                 changes={"tender": tender_number, "key": data.key, "payment": data.payment,
                          "request": req.number})
    return data.kind, doc


@transaction.atomic
def create_documents(data: TenderHandover) -> list[DocumentRef]:
    data = TenderHandover.model_validate(data)
    out = []
    for doc in data.docs:
        doc_type, existing = _existing(doc.key)
        if existing is not None:
            out.append(_ref(doc.key, doc_type, existing))
            continue
        try:
            with transaction.atomic():
                doc_type, created = _create_one(data.actor, doc, data.tender_number)
        except IntegrityError:
            # Параллельная передача с тем же ключом — берём созданное ею.
            doc_type, created = _existing(doc.key)
            if created is None:
                raise
        out.append(_ref(doc.key, doc_type, created))
    return out


# ── статусы ─────────────────────────────────────────────────────────────

def _replaced_by(doc_type: str, doc) -> ReplacedBy | None:
    from apps.bpp.services.selection import checks

    links = checks.alternative_links(doc_type, doc).get("replaced_by")
    if not links:
        return None
    return ReplacedBy(doc_type=links["result_type"], doc_id=links["result_id"],
                      number=links["result_number"], offer_number=links["offer_number"])


def _paid(invoice: Invoice) -> Decimal:
    total = (PaymentMark.objects.filter(invoice=invoice, cancelled_at__isnull=True)
             .aggregate(total=Sum("amount"))["total"])
    return money(total or Decimal("0"))


def _invoice_out(request_id: str, inv: Invoice) -> DocumentStatusOut:
    return DocumentStatusOut(
        request_id=request_id, doc_type="invoice", doc_id=str(inv.pk), number=inv.number,
        status=inv.status, amount=inv.amount, currency_code=inv.currency_code,
        counterparty_id=str(inv.counterparty_id) if inv.counterparty_id else None,
        agreement_id=str(inv.agreement_id) if inv.agreement_id else None,
        paid_amount=_paid(inv), is_advance=inv.is_advance,
        pay_after_receipt=inv.pay_after_receipt, due_date=inv.due_date,
        docs_required=inv.docs_required or {}, received_at=inv.received_at,
        tender_key=inv.tender_key, replaced_by=_replaced_by("invoice", inv))


def _agreement_out(request_id: str, agr: Agreement) -> DocumentStatusOut:
    return DocumentStatusOut(
        request_id=request_id, doc_type="agreement", doc_id=str(agr.pk), number=agr.number,
        status=agr.status, amount=agr.amount, currency_code=agr.currency_code,
        counterparty_id=str(agr.counterparty_id) if agr.counterparty_id else None,
        tender_key=agr.tender_key, replaced_by=_replaced_by("agreement", agr))


def documents_status(request_ids: list[str]) -> list[DocumentStatusOut]:
    """Договоры и счета по позициям ЗЗ (в том числе счета по договорам и
    документы, заменившие исходные альтернативой)."""
    keys = [key for key in (_uuid(i) for i in request_ids) if key]
    out: list[DocumentStatusOut] = []
    for req in PurchaseRequest.objects.filter(pk__in=keys).order_by("created_at"):
        rid = str(req.pk)
        agreements = (Agreement.objects.filter(items__request_item__request=req).distinct()
                      .order_by("created_at"))
        invoices = (Invoice.objects.filter(lines__request_item__request=req).distinct()
                    .order_by("created_at"))
        out += [_agreement_out(rid, agr) for agr in agreements]
        out += [_invoice_out(rid, inv) for inv in invoices]
    return out


def status_of_id(doc_type: str, doc_id) -> DocumentStatusOut | None:
    """Документ из тендера для слушателя смены статуса; прочие — ``None``."""
    if doc_type == "invoice":
        doc = Invoice.objects.select_related("agreement").filter(pk=doc_id).first()
        key = tender_key_of("invoice", doc)
        if not key:
            return None
        line = doc.lines.select_related("request_item").first()
        out = _invoice_out(str(line.request_item.request_id) if line else "", doc)
        return out.model_copy(update={"tender_key": key})
    doc = Agreement.objects.filter(pk=doc_id).first()
    key = tender_key_of("agreement", doc)
    if not key:
        return None
    item = doc.items.select_related("request_item").first()
    out = _agreement_out(str(item.request_item.request_id) if item else "", doc)
    return out.model_copy(update={"tender_key": key})


# ── приёмка и закрывающие ───────────────────────────────────────────────

@transaction.atomic
def set_acceptance(invoice_ids: list[str], *, received_at: date | None,
                   originals_at: date | None, originals_to: str, actor: TenderActor) -> None:
    """Отметка приёмки из тендера на счетах. ``received_at=None`` — приёмку
    отменили (срок оплаты «после приёмки» остаётся последним поставленным)."""
    keys = [key for key in (_uuid(i) for i in invoice_ids) if key]
    for inv in _tender_invoices(keys, lock=True):
        inv.received_at, inv.originals_at = received_at, originals_at
        inv.originals_to = (originals_to or "").strip()[:255]
        if received_at is not None and inv.pay_after_receipt:
            previous_due = inv.due_date
            inv.due_date = refdata.add_bank_days(received_at,
                                                 inv.postpay_days or POSTPAY_DEFAULT_DAYS)
            # Плановую дату, которую ФД поставил сам, приёмка не перебивает;
            # поставленную прошлой приёмкой (равна прежнему сроку) — сдвигает.
            if inv.planned_pay_date in (None, previous_due):
                inv.planned_pay_date = inv.due_date
        inv.version += 1
        inv.updated_by = actor.user_id
        inv.save()
        audit.record(inv, "acceptance_marked", actor_id=actor.user_id, changes={
            "received_at": received_at.isoformat() if received_at else None,
            "originals_at": originals_at.isoformat() if originals_at else None,
            "originals_to": inv.originals_to,
            "due_date": inv.due_date.isoformat() if inv.due_date else None})


@transaction.atomic
def attach_closing_docs(invoice_id: str, scans: list[ClosingFileIn], *,
                        actor: TenderActor) -> list[str]:
    """Сканы приёмки из тендера на счёт — правило D-13 держит БЗО: счёт «Ждёт
    закрывающих» и тип запрошен БУХ. Тот же файл второй раз не прикладывается."""
    key = _uuid(invoice_id)
    found = _tender_invoices([key], lock=True) if key else []
    inv = found[0] if found else None
    if inv is None:
        raise DomainError("E-NOT-FOUND", "Счёт не найден.", status=404)
    if inv.status != InvoiceStatus.AWAITING_DOCS:
        raise DomainError("E-STS-01", f"Счёт {inv.number} не ждёт закрывающих документов — "
                                      f"их запрашивает бухгалтер после оплаты (D-13).",
                          status=409)
    requested = {DOC_FILE_TYPES[k] for k, need in (inv.docs_required or {}).items()
                 if need and k in DOC_FILE_TYPES}
    out = []
    for scan in [ClosingFileIn.model_validate(s) for s in scans]:
        if scan.file_type not in requested:
            raise DomainError("E-FIL-06", f"По счёту {inv.number} бухгалтер не запрашивал "
                                          f"этот тип документа.", status=409)
        result = files.adopt_media_file("bpp.invoice", inv.pk, file_type=scan.file_type,
                                        media_file_id=scan.media_file_id,
                                        uploaded_by_id=actor.user_id)
        out.append(str(result["document_id"]))
        if result.get("created"):
            audit.record(inv, "closing_doc_from_tender", actor_id=actor.user_id,
                         changes={"file_type": scan.file_type, "name": scan.name})
    return out
