"""Мир этапа 5 для тестов: заявка с частями (товар, доставка, СМР), тендер на
приёме и предложения — те же числа, что у сценария «к-вскрытию»
``seed_tender_demo``.

- A — контрагент БЗО: все три позиции в KZT с НДС 16 %, доставка в цене,
  СМР 1 150 000, схема «аванс 30 %»;
- B — контрагент БЗО: позиции 1–2 (позицию 3 не предлагает) в USD без НДС,
  уголок — аналог и 3 т из 4, доставка 640 USD, СМР 2100 USD, предоплата;
- C — потенциальный поставщик с БИН: все позиции в KZT без НДС, доставка
  280 000, СМР 1 340 000, постоплата 15 дней;
- D — потенциальный, отказался; E — потенциальный, молчит.

Строки заявки, частей и тендера создаются прямо в таблицах (отправку в БЗО
и свёртку проверяют тесты этапа 1); предложения подаются сервисом портала.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

from django.utils import timezone

from apps.bpp.management.commands.seed_bpp_demo import bin_with_checksum
from apps.refdata.models import ExchangeRate
from apps.tender.models import (
    Invitation,
    SupplierProspect,
    Tender,
    TenderRequest,
    TenderRequestItem,
    TenderRequestPart,
)
from apps.tender.services.portal import access, offers
from apps.tender.services.tenders import schemes
from apps.tender.tests import helpers as h
from htqweb.tenancy.db import use_company

#: (наименование, кол-во, плановая цена) — позиции заявки.
ITEMS = (("Швеллер 12П", "10", "245000"), ("Уголок 50×5", "4", "215000"),
         ("Лист г/к 4 мм", "2", "285000"))
DELIVERY_PLAN, WORKS_PLAN = Decimal("350000"), Decimal("1200000")
USD_RATE = Decimal("515.20")


def portal_ctx(invitation: Invitation) -> SimpleNamespace:
    inv = Invitation.objects.get(pk=invitation.pk)
    return SimpleNamespace(invitation=inv, tender=inv.tender, binding=None)


def send(invitation: Invitation, data: dict) -> None:
    """Черновик и отправка предложения сервисом портала."""
    ctx = portal_ctx(invitation)
    offers.save_draft(ctx, {"version": offers.offer_view(ctx)["version"], **data})
    ctx = portal_ctx(invitation)
    offers.submit(ctx, {"version": offers.offer_view(ctx)["version"], "pd_consent": True})


def _lines(items, rows) -> list[dict]:
    out = []
    for item, (price, qty, analog) in zip(items, rows):
        if price is None:
            out.append({"item_id": str(item.pk), "participates": False})
        else:
            out.append({"item_id": str(item.pk), "participates": True, "price": price,
                        "qty": qty or str(item.qty), "is_analog": bool(analog),
                        "analog_note": analog or "",
                        "delivery_date": timezone.localdate() + timedelta(days=21)})
    return out


def build(slug: str, *, close: bool = True, rate_on=None, offers_from: str = "ABC",
          author: int = h.SN) -> SimpleNamespace:
    """``close`` — срок приёма в прошлое после подачи; ``rate_on`` — дата курса
    USD (по умолчанию сегодня); ``offers_from`` — кто из A, B, C подаёт."""
    with use_company(slug):
        n = TenderRequest.objects.count() + 1
        uom = h.pcs()
        goods_art, other_art = uuid.uuid4(), uuid.uuid4()
        need = timezone.localdate() + timedelta(days=30)
        req = TenderRequest.objects.create(
            number=f"ЗТ-2026-{900 + n:06d}", author_id=author, initiator_role="sn",
            project_id=uuid.uuid4(), article_id=goods_art, purchase_type="goods",
            status="in_tender", delivery_address="Астана, ул. Кенесары 40", need_date=need,
            justification="Металлопрокат для каркаса рампы", needs_delivery=True,
            delivery_article_id=other_art, delivery_plan_amount=DELIVERY_PLAN,
            needs_works=True, works_scope="Монтаж металлокаркаса",
            works_article_id=other_art, works_plan_amount=WORKS_PLAN, allow_analogs=True)
        parts = {kind: TenderRequestPart.objects.create(
            request=req, kind=kind, article_id=art, purchase_type=ptype,
            bpp_request_id=uuid.uuid4(), bpp_number=f"ЗЗ-{kind}-{n}", bpp_status="approved")
            for kind, art, ptype in (("goods", goods_art, "goods"),
                                     ("delivery", other_art, "works"),
                                     ("works", other_art, "works"))}
        items = [TenderRequestItem.objects.create(
            request=req, part=parts["goods"], line_no=i, name=name, uom_id=uom.id,
            qty=Decimal(qty), plan_price=Decimal(price), need_date=need,
            article_id=goods_art, bpp_request_item_id=uuid.uuid4())
            for i, (name, qty, price) in enumerate(ITEMS, start=1)]
        tender = Tender.objects.create(
            number=f"ТН-2026-{900 + n:06d}", request=req, author_id=author, status="intake",
            deadline_at=timezone.now() + timedelta(days=7), currency_code="KZT",
            delivery_terms="DAP Астана")
        schemes.replace(tender, "advance", advance_pct="30", actor_id=author)

        cp_a = h.counterparty(f"9{n:02d}0000000001", email=f"a{n}@metall.kz",
                              name="ТОО «Демо Металл»")
        cp_b = h.counterparty(f"9{n:02d}0000000002", email=f"b{n}@electro.kz",
                              name="ТОО «Демо Электро»")
        prospects = {key: SupplierProspect.objects.create(
            name=name, email=f"{key.lower()}{n}@supplier.kz", reg_number=reg, country_code="KZ")
            for key, name, reg in (("C", "ТОО «Демо Снаб»", bin_with_checksum(f"98{n:02d}0000003")),
                                   ("D", "ИП «Демо Склад»", ""),
                                   ("E", "ТОО «Демо Молчун»", ""))}

        def invite(key, *, cp=None, prospect=None) -> Invitation:
            return Invitation.objects.create(
                tender=tender, counterparty_id=cp.id if cp else None, prospect=prospect,
                email=(cp.email if cp else prospect.email), name=(cp.name if cp else prospect.name),
                token_hash=uuid.uuid4().hex + uuid.uuid4().hex, status="sent",
                sent_at=timezone.now())

        inv = {"A": invite("A", cp=cp_a), "B": invite("B", cp=cp_b),
               "C": invite("C", prospect=prospects["C"]), "D": invite("D", prospect=prospects["D"]),
               "E": invite("E", prospect=prospects["E"])}
        valid = timezone.localdate() + timedelta(days=45)
        payloads = {
            "A": {"currency_code": "KZT", "with_vat": True, "vat_rate": "16", "valid_until": valid,
                  "lines": _lines(items, [("238000", None, ""), ("219000", None, ""),
                                          ("279000", None, "")]),
                  "extras": {"delivery": {"included_in_price": True},
                             "works": {"amount": "1150000", "included_in_price": False}},
                  "payment_scheme": {"kind": "advance", "advance_pct": "30"}},
            "B": {"currency_code": "USD", "with_vat": False, "valid_until": valid,
                  "lines": _lines(items, [("452", None, ""), ("398", "3", "Уголок ст09Г2С"),
                                          (None, None, "")]),
                  "extras": {"delivery": {"amount": "640", "included_in_price": False},
                             "works": {"amount": "2100", "included_in_price": False}},
                  "payment_scheme": {"kind": "prepay"}},
            "C": {"currency_code": "KZT", "with_vat": False, "valid_until": valid,
                  "lines": _lines(items, [("262000", None, ""), ("229000", None, ""),
                                          ("301000", None, "")]),
                  "extras": {"delivery": {"amount": "280000", "included_in_price": False},
                             "works": {"amount": "1340000", "included_in_price": False}},
                  "payment_scheme": {"kind": "postpay", "postpay_days": 15},
                  "requisites": {"name": "ТОО «Демо Снаб»", "country_code": "KZ",
                                 "reg_number": prospects["C"].reg_number,
                                 "is_vat_payer": False, "contact_name": "Сейткали А.",
                                 "phone": "+77010000001", "email": prospects["C"].email}},
        }
        for key in offers_from:
            send(inv[key], payloads[key])
        decliner = portal_ctx(inv["D"])
        offers.decline(decliner, {"reason": "Нет нужного проката на складе"},
                       event=lambda kind, meta: access.log_event(decliner.invitation, kind,
                                                                 meta=meta))
        ExchangeRate.objects.update_or_create(
            currency_code="USD", on_date=rate_on or timezone.localdate(),
            defaults={"rate": USD_RATE, "source": "manual"})
        if close:
            Tender.objects.filter(pk=tender.pk).update(
                deadline_at=timezone.now() - timedelta(hours=1))
        tender.refresh_from_db()
        for row in inv.values():
            row.refresh_from_db()
        return SimpleNamespace(slug=slug, req=req, tender=tender, items=items, parts=parts,
                               inv=inv, cp={"A": cp_a, "B": cp_b}, prospects=prospects)
