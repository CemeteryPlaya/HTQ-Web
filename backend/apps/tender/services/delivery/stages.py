"""Стадии поставки по поставщику (T5.5; спека этапа 5, §3 T5.5; ТЗ «Оплата и
доставка», TND-040).

Данные — документы БЗО (``bpp.documents_status``: статусы, оплаты по отметкам
БУХ, замена альтернативой) и приёмки tender. Стадии:

``awaiting_documents`` — ни счёт не «К оплате» и далее, ни договор не
«Действует»; ``awaiting_shipment_payment`` — оплачено меньше доли этапов «до
отгрузки» схемы (у постоплаты доля 0); ``in_delivery`` — доля оплачена, приёмок
нет; ``partially_received`` / ``received`` — принято не всё / всё (товар по
количеству, СМР — «Работы приняты»; доставка принимается вместе с товаром);
``awaiting_final_payment`` — всё принято, оплачено меньше суммы; ``closed`` —
всё принято и все счета «Закрыт».

Документ, заменённый альтернативой БЗО (T-18), уступает место новому —
стадии считаются по нему, а поставщик показывает ссылку на замену.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from apps.bpp import interface as bpp
from apps.tender.models import (
    Award,
    PaymentScheme,
    PaymentTrigger,
    ReceiptLine,
    Tender,
)
from apps.tender.services.tenders import tenders
from apps.tender.services.tenders.ctx import Ctx

ZERO = Decimal("0")
LIVE_INVOICE = {"to_pay", "partially_paid", "paid", "awaiting_docs", "docs_provided", "closed"}
LIVE_AGREEMENT = {"active", "fulfilled"}
DEAD = {"cancelled", "replaced", "rejected", "not_payable"}


def _shipment_share(tender: Tender, offer) -> Decimal:
    scheme = (PaymentScheme.objects.filter(offer=offer).first()
              or PaymentScheme.objects.filter(tender=tender).first())
    if scheme is None:
        return Decimal("1")
    return sum((s.pct for s in scheme.stages.all()
                if s.trigger == PaymentTrigger.BEFORE_SHIPMENT), ZERO) / Decimal("100")


def received_by_award(tender: Tender) -> dict:
    out: dict = defaultdict(lambda: ZERO)
    for line in ReceiptLine.objects.filter(receipt__tender=tender,
                                           receipt__cancelled_at__isnull=True):
        out[line.award_id] += line.qty
    return out


def supplier_documents(tender: Tender) -> dict[str, list]:
    """Документы БЗО поставщиков тендера: свои (ключ передачи), счета по своим
    договорам и документы, заменившие свои альтернативой."""
    parts = [str(p.bpp_request_id) for p in tender.request.parts.exclude(bpp_request_id=None)]
    rows = bpp.documents_status(parts) if parts else []
    by_id = {row.doc_id: row for row in rows}
    out: dict[str, list] = defaultdict(list)
    for row in rows:
        if not row.tender_key:
            continue
        invitation = row.tender_key.split(":", 1)[0]
        chain = [row]
        seen = {row.doc_id}
        while chain[-1].replaced_by and chain[-1].replaced_by.doc_id in by_id \
                and chain[-1].replaced_by.doc_id not in seen:
            nxt = by_id[chain[-1].replaced_by.doc_id]
            seen.add(nxt.doc_id)
            chain.append(nxt)
        out[invitation] += chain
        agreements = {r.doc_id for r in chain if r.doc_type == "agreement"}
        out[invitation] += [r for r in rows if r.agreement_id in agreements
                            and r.doc_id not in seen]
    return out


def _stage(*, docs, paid, total, share, received_all, received_any) -> str:
    live = [d for d in docs if d.status not in DEAD]
    approved = any((d.doc_type == "invoice" and d.status in LIVE_INVOICE)
                   or (d.doc_type == "agreement" and d.status in LIVE_AGREEMENT) for d in live)
    invoices = [d for d in live if d.doc_type == "invoice"]
    if received_all and invoices and all(d.status == "closed" for d in invoices) \
            and paid >= total:
        return "closed"
    if received_all:
        return "awaiting_final_payment" if paid < total else "received"
    if received_any:
        return "partially_received"
    if not approved:
        return "awaiting_documents"
    return "in_delivery" if paid >= (total * share) else "awaiting_shipment_payment"


def delivery_of(tender: Tender) -> list[dict]:
    awards = list(tender.awards.select_related("offer__invitation", "line__item", "extra"))
    received = received_by_award(tender)
    docs = supplier_documents(tender)
    by_inv: dict = defaultdict(list)
    for award in awards:
        by_inv[award.offer.invitation_id].append(award)
    out = []
    for invitation_id, rows in by_inv.items():
        offer = rows[0].offer
        to_receive = [a for a in rows if a.line_id or (a.extra_id and a.extra.kind == "works")]
        received_all = bool(to_receive) and all(received[a.pk] >= a.qty for a in to_receive)
        received_any = any(received[a.pk] > 0 for a in to_receive)
        mine = docs.get(str(invitation_id), [])
        paid = sum((d.paid_amount for d in mine if d.doc_type == "invoice"
                    and d.status not in DEAD), ZERO)
        total = sum((a.amount for a in rows), ZERO)
        share = _shipment_share(tender, offer)
        stage = _stage(docs=mine, paid=paid, total=total, share=share,
                       received_all=received_all, received_any=received_any)
        out.append({
            "invitation_id": str(invitation_id), "supplier": offer.invitation.name,
            "currency_code": offer.currency_code, "stage": stage,
            "total": str(total), "paid": str(paid), "shipment_share": str(share),
            "documents": [{"doc_type": d.doc_type, "doc_id": d.doc_id, "number": d.number,
                           "status": d.status, "amount": _s(d.amount),
                           "paid_amount": str(d.paid_amount), "received_at": _s(d.received_at),
                           "replaced_by": d.replaced_by.model_dump() if d.replaced_by else None}
                          for d in mine],
            "awards": [{"award_id": str(a.pk), "kind": "line" if a.line_id else a.extra.kind,
                        "name": a.line.item.name if a.line_id else a.extra.get_kind_display(),
                        "qty": str(a.qty), "received": str(received[a.pk]),
                        "needs_receipt": a in to_receive} for a in rows],
        })
    return out


def _s(value) -> str | None:
    return None if value is None else str(value)


def delivery(ctx: Ctx, tender_id) -> dict:
    tender = tenders.get_visible(ctx, tender_id)
    return {"tender_id": str(tender.pk), "status": tender.status,
            "suppliers": delivery_of(tender)}


def all_closed(tender: Tender) -> bool:
    rows = delivery_of(tender)
    return bool(rows) and all(r["stage"] == "closed" for r in rows)


def any_moving(tender: Tender) -> bool:
    return any(r["stage"] not in ("awaiting_documents", "awaiting_shipment_payment")
               for r in delivery_of(tender))


__all__ = ["Award", "all_closed", "any_moving", "delivery", "delivery_of", "received_by_award",
           "supplier_documents"]
