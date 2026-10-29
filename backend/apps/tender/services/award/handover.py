"""Передача выбора в БЗО (T5.5; спека этапа 5, §3 T5.5; S5-10, S5-11, S5-13).

После «Выбор утверждён» автор передаёт выбор в БЗО одной транзакцией:

1. Контрагенты: у приглашения контрагента — он; потенциальный поставщик
   становится карточкой БЗО по реквизитам из портала
   (``bpp.create_counterparty_from_prospect``, без дубля по стране + рег.
   номеру); нет рег. номера — 422 ``E-TND-14``, ничего не создано.
2. Документ — на поставщика × часть заявки (ЗЗ): **договор**, если его сумма
   в KZT больше ``contract_threshold`` (1000 МРП на сегодня), иначе счёт без
   договора — порог на документ (S5-10, ответ ФД 20.10; BR-040: граница —
   счёт). Схема оплаты — поставщика, нет её — тендера (S5-11).
3. Строки «в цене» (доставка или СМР с суммой 0) документа не дают; часть без
   единой платной строки — её ЗЗ закрывается (резерв освобождается).
4. Документы создаёт ``bpp.create_documents_from_tender`` от имени закупщика;
   ``Handover`` — по каждому документу.

Повторная передача (двойной клик, обрыв сети) отдаёт уже созданное.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.bpp import interface as bpp
from apps.files import interface as files
from apps.refdata import interface as refdata
from apps.tender.models import (
    Handover,
    PaymentScheme,
    SupplierProspect,
    Tender,
    TenderRequestStatus,
    TenderStatus,
)
from apps.tender.services.core import audit
from apps.tender.services.core.errors import check_version
from apps.tender.services.tenders import tenders
from apps.tender.services.tenders.ctx import Ctx

ZERO = Decimal("0")
OFFER_OWNER, OFFER_FILE_TYPE = "tender.offer", "tender_offer"
DONE = (TenderStatus.HANDED_OVER, TenderStatus.DELIVERY, TenderStatus.CLOSED)


def _counterparty(tender: Tender, invitation, offer) -> str:
    if invitation.counterparty_id:
        return str(invitation.counterparty_id)
    prospect = SupplierProspect.objects.select_for_update().get(pk=invitation.prospect_id)
    if prospect.counterparty_id:
        return str(prospect.counterparty_id)
    req = offer.requisites or {}
    ref = bpp.create_counterparty_from_prospect(bpp.ProspectIn(
        name=(req.get("name") or prospect.name)[:500],
        country_code=(req.get("country_code") or prospect.country_code or "KZ")[:2],
        reg_number=(req.get("reg_number") or prospect.reg_number or "")[:30],
        is_vat_payer=bool(req.get("is_vat_payer")),
        contact_name=(req.get("contact_name") or "")[:255],
        phone=(req.get("phone") or "")[:64],
        email=(req.get("email") or prospect.email or "")[:254],
        tender_number=tender.number), actor=bpp.TenderActor(user_id=tender.author_id))
    prospect.counterparty_id = ref.id
    prospect.save(update_fields=["counterparty_id", "updated_at"])
    return ref.id


def _payment(tender: Tender, offer) -> tuple[str, int | None]:
    scheme = (PaymentScheme.objects.filter(offer=offer).first()
              or PaymentScheme.objects.filter(tender=tender).first())
    kind = scheme.kind if scheme else "prepay"
    return kind, (scheme.postpay_days if scheme and kind == "postpay" else None)


def result_of(tender: Tender) -> dict:
    rows = tender.handovers.select_related("invitation").order_by("created_at")
    return {"tender_id": str(tender.pk), "status": tender.status,
            "documents": [{"invitation_id": str(h.invitation_id), "supplier": h.invitation.name,
                           "part_id": str(h.part_id), "doc_type": h.bpp_document_type,
                           "doc_id": str(h.bpp_document_id), "number": h.bpp_number}
                          for h in rows]}


@transaction.atomic
def handover(ctx: Ctx, tender_id, *, expected_version: int | None) -> dict:
    tender = tenders.get_own(ctx, tender_id, "Передавать в БЗО")
    if tender.status in DONE:
        return result_of(tender)               # повтор — уже переданное
    if tender.status != TenderStatus.AWARDED:
        raise tenders.state_error("передать в БЗО", tender)
    check_version(tender, expected_version)

    awards = list(tender.awards.select_related("offer__invitation", "line__item", "extra"))
    groups: dict[tuple, list] = defaultdict(list)
    for award in awards:
        if award.amount > 0:                   # «в цене» документа не даёт
            groups[(award.offer.invitation_id, str(award.part_id))].append(award)
    parts = {str(p.pk): p for p in tender.request.parts.filter(excluded_at__isnull=True)}
    threshold = refdata.contract_threshold(timezone.localdate())

    docs = []
    for (invitation_id, part_id), rows in groups.items():
        offer = rows[0].offer
        invitation = offer.invitation
        part = parts[part_id]
        total_kzt = sum((a.amount_kzt or ZERO) for a in rows)
        payment, days = _payment(tender, offer)
        docs.append(bpp.HandoverDocIn(
            key=f"{invitation_id}:{part_id}", bpp_request_id=str(part.bpp_request_id),
            counterparty_id=_counterparty(tender, invitation, offer),
            currency_code=offer.currency_code, with_vat=offer.with_vat,
            vat_rate=offer.vat_rate if offer.with_vat else None,
            kind="agreement" if total_kzt > threshold else "invoice",
            payment=payment, postpay_days=days,
            lines=[bpp.HandoverLineIn(
                bpp_request_item_id=(str(a.line.item.bpp_request_item_id)
                                     if a.line_id and a.line.item.bpp_request_item_id else None),
                qty=a.qty, amount=a.amount) for a in rows],
            offer_media_file_ids=[f["media_file_id"] for f in
                                  files.current_files(OFFER_OWNER, offer.pk, OFFER_FILE_TYPE)]))

    refs = bpp.create_documents_from_tender(bpp.TenderHandover(
        actor=bpp.TenderActor(user_id=tender.author_id), tender_number=tender.number,
        docs=docs)) if docs else []
    for ref in refs:
        invitation_id, part_id = ref.key.split(":", 1)
        Handover.objects.get_or_create(
            tender=tender, invitation_id=invitation_id, part_id=part_id,
            defaults={"bpp_document_type": ref.doc_type, "bpp_document_id": ref.doc_id,
                      "bpp_number": ref.number, "created_by": ctx.user_id,
                      "updated_by": ctx.user_id})

    used = {part_id for _inv, part_id in groups}
    closed = [p for key, p in parts.items() if key not in used and p.bpp_request_id]
    if closed:
        bpp.cancel_requests_from_tender(
            [str(p.bpp_request_id) for p in closed], actor=bpp.TenderActor(user_id=tender.author_id),
            comment=f"Не выбрано в тендере {tender.number} (в цене у поставщика или без "
                    f"выбора) — резерв освобождён.")

    tender.status = TenderStatus.HANDED_OVER
    tenders._touch(tender, ctx.user_id)
    req = tender.request
    if req.status == TenderRequestStatus.IN_TENDER:
        tenders._set_request_status(req, TenderRequestStatus.HANDED_OVER, ctx.user_id,
                                    "handed_over", tender)
    audit.record(tender, "handover", actor_id=ctx.user_id,
                 changes={"documents": [r.number for r in refs],
                          "closed_parts": [str(p.pk) for p in closed]})
    out = result_of(tender)
    out["closed_parts"] = [str(p.pk) for p in closed]
    return out
