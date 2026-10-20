"""Таблица сравнения предложений (T5.1; спека этапа 5, §1, §3 T5.1; ТЗ TND-020,
TND-021).

Позиции — строками, поставщики — колонками, отдельными строками доставка и
СМР. Сравниваются отправленные версии на момент вскрытия (после вскрытия
портал правку не принимает). Суммы — к оплате в валюте предложения и в KZT по
курсу НБРК последнего дня не позже даты вскрытия (T-12); нет курса — суммы в
KZT пусты и предупреждение ``no_rate``.

- **Общий набор** — позиции, которые предложили все участвующие; итог «по
  общему набору» = его строки + доставка + СМР целиком (TND-021), «полный» —
  все свои строки + доставка + СМР. Покрытие — «N из M».
- **План** строки поставщика — плановая цена × предложенное количество;
  доставка и СМР — плановые суммы заявки. Экономия = план − предложение
  (удорожание — отрицательная).
- **Самый дешёвый** — по цене за единицу в KZT у позиции, по сумме — у
  доставки и СМР; поставщики без курса не участвуют.
"""

from __future__ import annotations

from decimal import Decimal

from django.utils import timezone

from apps.files import interface as files
from apps.refdata import interface as refdata
from apps.tender.models import (
    ExtraKind,
    InvitationStatus,
    Offer,
    OfferStatus,
    PortalEvent,
    PortalEventKind,
    Tender,
)
from apps.tender.services.tenders import schemes, tenders
from apps.tender.services.tenders.ctx import Ctx

from . import money
from .opening import require_opened

OFFER_OWNER, OFFER_FILE_TYPE = "tender.offer", "tender_offer"
ZERO = Decimal("0")


def _str(value) -> str | None:
    return None if value is None else str(value)


def comparison(ctx: Ctx, tender_id) -> dict:
    tender = tenders.get_visible(ctx, tender_id)
    require_opened(tender)
    return build(tender)


def offers_of(tender: Tender) -> list[Offer]:
    """Отправленные версии участников тендера — то, что вскрыто."""
    return list(Offer.objects.filter(invitation__tender=tender, status=OfferStatus.SUBMITTED)
                .select_related("invitation")
                .prefetch_related("lines", "extras", "payment_schemes__stages")
                .order_by("invitation__created_at"))


def rates_for(tender: Tender, offers: list[Offer]) -> dict:
    """Курс на дату вскрытия по каждой валюте предложений (``RateOut`` или ``None``)."""
    return {code: refdata.exchange_rate_on_or_before(code, tender.rate_date)
            for code in {o.currency_code for o in offers}}


def requested_extras(tender: Tender) -> list[tuple[str, Decimal | None]]:
    req = tender.request
    out = []
    if req.needs_delivery:
        out.append((ExtraKind.DELIVERY, req.delivery_plan_amount))
    if req.needs_works:
        out.append((ExtraKind.WORKS, req.works_plan_amount))
    return out


def line_amount(offer: Offer, line) -> Decimal:
    return money.gross(line.price * line.qty, with_vat=offer.with_vat, vat_rate=offer.vat_rate)


def extra_amount(offer: Offer, extra) -> Decimal:
    if extra.included_in_price:
        return ZERO
    return money.gross(extra.amount or ZERO, with_vat=offer.with_vat, vat_rate=offer.vat_rate)


def _declined(tender: Tender) -> list[dict]:
    rows = []
    for inv in tender.invitations.filter(status=InvitationStatus.DECLINED).order_by("created_at"):
        event = (PortalEvent.objects.filter(invitation=inv, kind=PortalEventKind.DECLINED)
                 .order_by("-created_at").first())
        rows.append({"invitation_id": str(inv.pk), "name": inv.name,
                     "reason": (event.meta or {}).get("reason", "") if event else ""})
    return rows


def build(tender: Tender) -> dict:
    items = list(tender.request.items.order_by("line_no"))
    offers = offers_of(tender)
    rates = rates_for(tender, offers)
    uoms = refdata.uom_brief(list({str(i.uom_id) for i in items})) if items else {}
    lines = {o.pk: {line.item_id: line for line in o.lines.all()} for o in offers}
    extras = {o.pk: {e.kind: e for e in o.extras.all()} for o in offers}
    offered = {o.pk: {item_id for item_id, line in lines[o.pk].items()
                      if line.participates and line.price is not None} for o in offers}
    common = {i.pk for i in items if offers and all(i.pk in offered[o.pk] for o in offers)}

    def rate(o: Offer) -> Decimal | None:
        found = rates.get(o.currency_code)
        return found.rate if found else None

    item_rows = []
    for item in items:
        cells, best, best_price = {}, None, None
        for o in offers:
            line = lines[o.pk].get(item.pk)
            if item.pk not in offered[o.pk]:
                cells[str(o.invitation_id)] = {"participates": False}
                continue
            amount = line_amount(o, line)
            unit = money.to_kzt(line.price, rate(o))
            cells[str(o.invitation_id)] = {
                "line_id": str(line.pk), "participates": True, "price": str(line.price),
                "qty": str(line.qty), "partial_qty": line.qty < item.qty,
                "amount": str(amount), "amount_kzt": _str(money.to_kzt(amount, rate(o))),
                "unit_price_kzt": _str(unit),
                "delivery_date": line.delivery_date.isoformat() if line.delivery_date else None,
                "is_analog": line.is_analog, "analog_note": line.analog_note,
                "comment": line.comment}
            if unit is not None and (best_price is None or unit < best_price):
                best, best_price = str(o.invitation_id), unit
        uom = uoms.get(str(item.uom_id)) or {}
        item_rows.append({
            "item_id": str(item.pk), "line_no": item.line_no, "name": item.name,
            "specs": item.specs,
            "uom": {"code": uom.get("code", ""), "short_name": uom.get("short_name", "")},
            "qty": str(item.qty), "plan_price": str(item.plan_price),
            "plan_amount": str(money.money(item.plan_price * item.qty)),
            "in_common_set": item.pk in common, "offers": cells,
            "cheapest_invitation_id": best})

    extra_rows = []
    for kind, plan in requested_extras(tender):
        cells, best, best_sum = {}, None, None
        for o in offers:
            extra = extras[o.pk].get(kind)
            if extra is None:
                cells[str(o.invitation_id)] = None
                continue
            amount = extra_amount(o, extra)
            in_kzt = money.to_kzt(amount, rate(o))
            cells[str(o.invitation_id)] = {
                "extra_id": str(extra.pk), "included_in_price": extra.included_in_price,
                "amount": str(amount), "amount_kzt": _str(in_kzt), "note": extra.note}
            if in_kzt is not None and (best_sum is None or in_kzt < best_sum):
                best, best_sum = str(o.invitation_id), in_kzt
        extra_rows.append({"kind": kind, "plan_amount": _str(plan), "offers": cells,
                           "cheapest_invitation_id": best})

    plans = {kind: plan or ZERO for kind, plan in requested_extras(tender)}
    today = timezone.localdate()
    warnings: list[dict] = []
    suppliers = []
    for o in offers:
        found = rates.get(o.currency_code)
        r = found.rate if found else None
        own = [(item, lines[o.pk][item.pk]) for item in items if item.pk in offered[o.pk]]
        common_rows = [(item, line) for item, line in own if item.pk in common]
        extras_sum = sum((extra_amount(o, e) for e in extras[o.pk].values()), ZERO)
        total_common = money.to_kzt(
            sum((line_amount(o, line) for _i, line in common_rows), ZERO) + extras_sum, r)
        total_full = money.to_kzt(
            sum((line_amount(o, line) for _i, line in own), ZERO) + extras_sum, r)
        plan_common = (sum((money.money(item.plan_price * line.qty) for item, line in common_rows),
                           ZERO) + sum(plans.get(kind, ZERO) for kind in extras[o.pk]))
        valid_expired = o.valid_until is not None and o.valid_until < today
        if r is None:
            warnings.append({"code": "no_rate", "invitation_id": str(o.invitation_id),
                             "currency_code": o.currency_code})
        if valid_expired:
            warnings.append({"code": "valid_expired", "invitation_id": str(o.invitation_id),
                             "valid_until": o.valid_until.isoformat()})
        suppliers.append({
            "invitation_id": str(o.invitation_id), "name": o.invitation.name,
            "counterparty_id": _str(o.invitation.counterparty_id),
            "prospect_id": _str(o.invitation.prospect_id),
            "offer_id": str(o.pk), "offer_number": o.number,
            "currency_code": o.currency_code, "rate": _str(r),
            "rate_on": found.on_date.isoformat() if found else None,
            "with_vat": o.with_vat, "vat_rate": _str(o.vat_rate),
            "valid_until": o.valid_until.isoformat() if o.valid_until else None,
            "valid_expired": valid_expired,
            "payment_scheme": schemes.out(o.payment_schemes.first()),
            "coverage": {"offered": len(offered[o.pk]), "total": len(items)},
            "total_common_kzt": _str(total_common), "total_full_kzt": _str(total_full),
            "saving_common_kzt": _str(None if total_common is None
                                      else money.money(plan_common - total_common)),
            "files": [{"id": str(f["document_id"]), "name": f["name"], "size": f["size"]}
                      for f in files.current_files(OFFER_OWNER, o.pk, OFFER_FILE_TYPE)],
            "requisites": o.requisites or {}, "extra_terms": o.extra_terms})

    return {"tender_id": str(tender.pk), "rate_date": tender.rate_date.isoformat(),
            "opened_at": tender.opened_at.isoformat(), "suppliers": suppliers,
            "items": item_rows, "extras": extra_rows,
            "totals": {"declined": _declined(tender), "suppliers": len(suppliers)},
            "warnings": warnings}


def offer_file_link(ctx: Ctx, tender_id, offer_id, document_id, *, ip: str | None,
                    user_agent: str) -> str:
    """Ссылка на файл КП вскрытого предложения: 302 на временную ссылку
    подсистемы файлов, выдача журналируется (``file_downloaded``, IP)."""
    from django.db import transaction

    from htqweb.errors import DomainError

    tender = tenders.get_visible(ctx, tender_id)
    require_opened(tender)
    gone = DomainError("E-NOT-FOUND", "Файл не найден.", status=404)
    offer = (Offer.objects.filter(pk=tenders._key(offer_id), invitation__tender=tender,
                                  number__isnull=False).first()
             if tenders._key(offer_id) else None)
    if offer is None:
        raise gone
    known = {str(f["document_id"]) for f in files.current_files(OFFER_OWNER, offer.pk,
                                                                 OFFER_FILE_TYPE)}
    if str(document_id) not in known:
        raise gone
    try:
        with transaction.atomic():
            return files.download_link(OFFER_OWNER, offer.pk, document_id, actor_id=ctx.user_id,
                                       ip=ip, user_agent=user_agent)
    except files.FilesError:
        raise gone from None
