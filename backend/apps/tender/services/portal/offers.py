"""Предложение поставщика на портале (T3.3; план этапа 3, §1, §2 T3.3;
мастер-план T-21…T-26).

Контекст ``ctx`` — то, что собирает ``access.require_device`` (T3.2):
``ctx.invitation``, ``ctx.tender``. Проверку токена и устройства делает
вызывающий; здесь — срок и статус тендера, правила строк и переходы.

**Срок** — время сервера: правка, отправка, отзыв и отказ после
``deadline_at`` или при статусе тендера ≠ «Приём предложений» — 409
``E-TND-05``. Проверка — под ``select_for_update`` тендера и приглашения в
той же транзакции, что запись.

**Версии.** У приглашения один черновик; «Отправить» делает его версией
``number = n + 1`` (прежняя отправленная — «Заменено»). Правка после
отправки заводит черновик-копию последней отправленной версии. ``version``
в теле сверяется с тем предложением, которое поставщик видит: черновиком,
а если его нет — последней версией.

**События** портала (``offer_saved``, ``offer_submitted``,
``offer_withdrawn``, ``declined``) пишет ``event(kind, meta)`` вызывающего
(``access.record_event`` T3.2) в той же транзакции; ``meta`` — без токенов и
секретов.

**Ответы — белым списком** (``offer_view``/``offer_out``): ни плановых цен
заявки, ни других участников.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.db import IntegrityError, transaction
from django.db.models import Max
from django.utils import timezone

from apps.bpp import interface as bpp
from apps.files import interface as files
from apps.refdata import interface as refdata
from apps.tender.models import (
    ExtraKind,
    Invitation,
    InvitationStatus,
    Offer,
    OfferExtra,
    OfferLine,
    OfferStatus,
    PaymentKind,
    PaymentScheme,
    PaymentStage,
    Tender,
    TenderRequestItem,
    TenderStatus,
)
from apps.tender.services.core.errors import check_version
from apps.tender.services.tenders import schemes
from htqweb.errors import DomainError

from .actor import portal_actor

Event = Callable[[str, dict], None]

#: Владелец файлов КП в ``apps.files`` (``file_owners.py``) и тип файла.
OFFER_OWNER = "tender.offer"
OFFER_FILE_TYPE = "tender_offer"

COMMENT_MIN = 10
TEXT_MAX = 2000
TERMS_MAX = 4000
MONEY_STEP, QTY_STEP, PCT_STEP = Decimal("0.01"), Decimal("0.001"), Decimal("0.01")
MONEY_MAX = Decimal("1e16")
CURRENCY = re.compile(r"^[A-Z]{3}$")
#: Реквизиты поставщика (план этапа 3, §2 T3.3) и их предел длины.
REQUISITES = {"name": 500, "country_code": 2, "reg_number": 30, "contact_name": 255,
              "phone": 64, "email": 254}


def _no_event(kind: str, meta: dict) -> None:  # noqa: ARG001 — заглушка для чтения
    return None


# ── ошибки ──────────────────────────────────────────────────────────────

def _bad(field_name: str, text: str, *, code: str = "E-VAL-01") -> DomainError:
    return DomainError(code, f"{text[:1].upper()}{text[1:]}.",
                       fields=[{"field": field_name, "message": text}])


def closed() -> DomainError:
    return DomainError("E-TND-05", "Приём предложений завершён.", status=409)


def _declined() -> DomainError:
    return DomainError("E-STS-01", "Вы отказались от участия в этом тендере — предложение "
                                   "больше не принимается.", status=409)


# ── срок и блокировки ───────────────────────────────────────────────────

def intake_open(tender: Tender) -> bool:
    """Приём идёт: статус «Приём предложений» и срок по часам сервера."""
    return (tender.status == TenderStatus.INTAKE and tender.deadline_at is not None
            and tender.deadline_at > timezone.now())


def _lock(ctx) -> tuple[Tender, Invitation]:
    """Тендер и приглашение под блокировкой; приём закрыт — E-TND-05,
    отказ от участия — E-STS-01."""
    tender = Tender.objects.select_for_update().select_related("request").get(pk=ctx.tender.pk)
    inv = Invitation.objects.select_for_update().get(pk=ctx.invitation.pk)
    if inv.revoked_at is not None:
        raise DomainError("E-NOT-FOUND", "Ссылка недействительна.", status=404)
    if not intake_open(tender):
        raise closed()
    if inv.status == InvitationStatus.DECLINED:
        raise _declined()
    return tender, inv


# ── чтение ──────────────────────────────────────────────────────────────

def _draft(inv: Invitation) -> Offer | None:
    return inv.offers.filter(status=OfferStatus.DRAFT).first()


def _last_sent(inv: Invitation) -> Offer | None:
    return inv.offers.filter(number__isnull=False).order_by("-number").first()


def _submitted(inv: Invitation) -> Offer | None:
    return inv.offers.filter(status=OfferStatus.SUBMITTED).first()


def _current(inv: Invitation) -> Offer | None:
    """Предложение, которое видит поставщик: черновик, иначе последняя версия."""
    return _draft(inv) or _last_sent(inv)


def _items(tender: Tender) -> list[TenderRequestItem]:
    return list(tender.request.items.order_by("line_no"))


def _requested_extras(tender: Tender) -> list[str]:
    req = tender.request
    return ([ExtraKind.DELIVERY] if req.needs_delivery else []) + (
        [ExtraKind.WORKS] if req.needs_works else [])


def locked_requisites(inv: Invitation) -> bool:
    """Реквизиты контрагента БЗО — только чтение (их ведёт закупщик)."""
    return inv.counterparty_id is not None


def _initial_requisites(inv: Invitation) -> dict:
    if inv.counterparty_id is not None:
        card = bpp.counterparty_brief([str(inv.counterparty_id)]).get(
            str(inv.counterparty_id)) or {}
        return {"name": card.get("name") or inv.name,
                "country_code": card.get("country_code") or "",
                "reg_number": card.get("reg_number") or "", "is_vat_payer": None,
                "contact_name": card.get("contact_person") or "",
                "phone": card.get("phone") or "", "email": card.get("email") or inv.email}
    prospect = inv.prospect
    return {"name": prospect.name if prospect else inv.name,
            "country_code": prospect.country_code if prospect else "",
            "reg_number": prospect.reg_number if prospect else "", "is_vat_payer": None,
            "contact_name": "", "phone": "", "email": inv.email}


def _blank(inv: Invitation, tender: Tender) -> Offer:
    offer = Offer.objects.create(invitation=inv, currency_code=tender.currency_code,
                                 requisites=_initial_requisites(inv))
    OfferLine.objects.bulk_create([OfferLine(offer=offer, item=item, participates=True,
                                             qty=item.qty) for item in _items(tender)])
    OfferExtra.objects.bulk_create([OfferExtra(offer=offer, kind=kind)
                                    for kind in _requested_extras(tender)])
    return offer


def _copy(src: Offer, inv: Invitation, tender: Tender) -> Offer:
    """Черновик-копия отправленной версии: шапка, строки, доставка/СМР, схема.
    Реквизиты контрагента — заново из карточки БЗО."""
    requisites = (_initial_requisites(inv) if locked_requisites(inv)
                  else dict(src.requisites))
    offer = Offer.objects.create(
        invitation=inv, currency_code=src.currency_code, with_vat=src.with_vat,
        vat_rate=src.vat_rate, delivery_cost=src.delivery_cost,
        delivery_included=src.delivery_included, works_cost=src.works_cost,
        works_note=src.works_note, valid_until=src.valid_until, extra_terms=src.extra_terms,
        requisites=requisites, pd_consent_at=src.pd_consent_at)
    lines = {line.item_id: line for line in src.lines.all()}
    OfferLine.objects.bulk_create([
        OfferLine(offer=offer, item=item, participates=old.participates, price=old.price,
                  qty=old.qty, delivery_date=old.delivery_date, is_analog=old.is_analog,
                  analog_note=old.analog_note, comment=old.comment)
        if (old := lines.get(item.pk)) else
        OfferLine(offer=offer, item=item, participates=True, qty=item.qty)
        for item in _items(tender)])
    extras = {extra.kind: extra for extra in src.extras.all()}
    OfferExtra.objects.bulk_create([
        OfferExtra(offer=offer, kind=kind, amount=old.amount,
                   included_in_price=old.included_in_price, note=old.note)
        if (old := extras.get(kind)) else OfferExtra(offer=offer, kind=kind)
        for kind in _requested_extras(tender)])
    scheme = src.payment_schemes.first()
    if scheme is not None:
        _write_scheme(offer, scheme.kind, [
            {"order": s.order, "trigger": s.trigger, "pct": s.pct, "days": s.days}
            for s in scheme.stages.order_by("order")], scheme.postpay_days)
    # Файлы КП — копиями: у отправленной версии остаются её файлы, черновик
    # получает свои (``doc_map`` — «документ версии → документ черновика»,
    # по нему удаление адресует копию).
    offer.doc_map = {}
    sources = files.current_files(OFFER_OWNER, src.pk, OFFER_FILE_TYPE)
    if sources:
        actor = portal_actor()
        for row in sources:
            copied = files.adopt_media_file(OFFER_OWNER, offer.pk, file_type=OFFER_FILE_TYPE,
                                            media_file_id=row["media_file_id"],
                                            uploaded_by_id=actor)
            offer.doc_map[str(row["document_id"])] = copied["document_id"]
    return offer


def get_draft(invitation: Invitation, tender: Tender | None = None) -> Offer:
    """Черновик приглашения — или новый: копия последней отправленной версии,
    иначе пустой по позициям заявки. Два одновременных запроса не заведут
    двух черновиков (частичный уникальный индекс)."""
    tender = tender or invitation.tender
    found = _draft(invitation)
    if found is not None:
        return found
    source = _last_sent(invitation)
    try:
        with transaction.atomic():
            return _copy(source, invitation, tender) if source else _blank(invitation, tender)
    except IntegrityError:
        found = _draft(invitation)
        if found is None:
            raise
        return found


#: Поля предложения, когда его нет (приём закрыт, а поставщик ничего не
#: сохранял) — форма получает те же ключи с пустыми значениями.
_EMPTY = {"id": None, "number": None, "status": None, "version": None,
          "submitted_at": None, "currency_code": None, "with_vat": None, "vat_rate": None,
          "valid_until": None, "extra_terms": "", "requisites": {}, "pd_consent": False,
          "pd_consent_at": None, "lines": [], "extras": [], "payment_scheme": None}


def offer_view(ctx) -> dict:
    """Ответ ``GET``/``PUT offer`` и переходов: текущее предложение (черновик,
    иначе последняя версия) плоским объектом + признаки и история версий.
    Пока приём идёт и отказа нет, без предложения заводится черновик.

    ``editable`` — черновик можно менять сейчас (приём идёт, отказа нет);
    ``intake_open`` — приём по тендеру идёт; ``requisites_readonly`` —
    реквизиты контрагента БЗО; ``can_withdraw`` — есть отправленная версия."""
    tender = Tender.objects.select_related("request").get(pk=ctx.tender.pk)
    inv = Invitation.objects.get(pk=ctx.invitation.pk)
    declined = inv.status == InvitationStatus.DECLINED
    open_ = intake_open(tender)
    editable = open_ and not declined
    offer = _current(inv)
    if offer is None and editable:
        offer = get_draft(inv, tender)
    return {
        **(offer_out(offer, tender, inv) if offer else _EMPTY),
        "editable": editable, "intake_open": open_, "declined": declined,
        "invitation_status": inv.status,
        "requisites_readonly": locked_requisites(inv),
        "can_withdraw": editable and _submitted(inv) is not None,
        "history": [{"number": o.number, "status": o.status,
                     "submitted_at": o.submitted_at.isoformat() if o.submitted_at else None}
                    for o in inv.offers.filter(number__isnull=False).order_by("-number")],
    }


def _str(value) -> str | None:
    return None if value is None else str(value)


def _date(value) -> str | None:
    return value.isoformat() if value else None


def offer_out(offer: Offer, tender: Tender, inv: Invitation) -> dict:
    """Предложение для поставщика — только перечисленные ключи."""
    lines = list(offer.lines.select_related("item").order_by("item__line_no"))
    uoms = refdata.uom_brief(list({str(line.item.uom_id) for line in lines}))
    scheme = offer.payment_schemes.first()
    requisites = offer.requisites or {}
    return {
        "id": str(offer.pk), "number": offer.number, "status": offer.status,
        "version": offer.version,
        "submitted_at": offer.submitted_at.isoformat() if offer.submitted_at else None,
        "currency_code": offer.currency_code, "with_vat": offer.with_vat,
        "vat_rate": _str(offer.vat_rate), "valid_until": _date(offer.valid_until),
        "extra_terms": offer.extra_terms,
        "requisites": {key: requisites.get(key) for key in (*REQUISITES, "is_vat_payer")},
        "pd_consent": offer.pd_consent_at is not None,
        "pd_consent_at": offer.pd_consent_at.isoformat() if offer.pd_consent_at else None,
        "lines": [{
            "item_id": str(line.item_id), "line_no": line.item.line_no,
            "name": line.item.name, "specs": line.item.specs,
            "uom": {"code": uoms.get(str(line.item.uom_id), {}).get("code"),
                    "short_name": uoms.get(str(line.item.uom_id), {}).get("short_name")},
            "qty_requested": str(line.item.qty),
            "need_date": _date(line.item.need_date or tender.request.need_date),
            "participates": line.participates, "price": _str(line.price),
            "qty": _str(line.qty), "delivery_date": _date(line.delivery_date),
            "is_analog": line.is_analog, "analog_note": line.analog_note,
            "comment": line.comment,
        } for line in lines],
        "extras": [{"kind": e.kind, "amount": _str(e.amount),
                    "included_in_price": e.included_in_price, "note": e.note}
                   for e in offer.extras.order_by("kind")],
        "payment_scheme": schemes.out(scheme),
    }


# ── проверки полей ──────────────────────────────────────────────────────

def _decimal(field_name: str, value, *, step: Decimal, label: str,
             allow_zero: bool = False) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        number = Decimal(str(value)).quantize(step, rounding=ROUND_HALF_UP)
    except InvalidOperation:
        raise _bad(field_name, f"{label}: нужно число") from None
    if (number < 0 if allow_zero else number <= 0) or number >= MONEY_MAX:
        raise _bad(field_name, f"{label}: нужно число больше нуля" if not allow_zero
                   else f"{label}: число не меньше нуля")
    return number


def _as_date(field_name: str, value) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise _bad(field_name, "дата в формате ГГГГ-ММ-ДД") from None


def _text(value, limit: int) -> str:
    return (value or "").strip()[:limit]


def _apply_header(offer: Offer, data: dict) -> None:
    if "currency_code" in data:
        code = (data["currency_code"] or "").strip().upper()
        if not CURRENCY.match(code):
            raise _bad("currency_code", "код валюты — три латинские буквы")
        offer.currency_code = code
    if "with_vat" in data and data["with_vat"] is not None:
        offer.with_vat = bool(data["with_vat"])
    if "vat_rate" in data:
        rate = _decimal("vat_rate", data["vat_rate"], step=PCT_STEP, label="ставка НДС",
                        allow_zero=True)
        if rate is not None and rate > 100:
            raise _bad("vat_rate", "ставка НДС — не больше 100 %")
        offer.vat_rate = rate
    if not offer.with_vat:
        offer.vat_rate = None
    if "valid_until" in data:
        offer.valid_until = _as_date("valid_until", data["valid_until"])
    if "extra_terms" in data:
        offer.extra_terms = _text(data["extra_terms"], TERMS_MAX)


def _apply_lines(offer: Offer, tender: Tender, rows: list[dict]) -> None:
    """Строки по позициям ЭТОЙ заявки: количество ≤ запрошенного, цена > 0,
    аналог — только если разрешён (E-TND-09), частичное предложение (не все
    позиции или не всё количество) — только если разрешено (E-TND-09)."""
    req = tender.request
    items = {str(item.pk): item for item in _items(tender)}
    lines = {str(line.item_id): line for line in offer.lines.all()}
    seen: set[str] = set()
    for index, row in enumerate(rows):
        where = f"lines[{index}]"
        key = str(row.get("item_id") or "")
        item = items.get(key)
        if item is None:
            raise _bad(f"{where}.item_id", "позиция не из этой заявки")
        if key in seen:
            raise _bad(f"{where}.item_id", "позиция указана дважды")
        seen.add(key)
        line = lines.get(key) or OfferLine(offer=offer, item=item)
        participates = bool(row.get("participates", line.participates))
        price = _decimal(f"{where}.price", row.get("price", line.price), step=MONEY_STEP,
                         label="цена за единицу")
        qty = _decimal(f"{where}.qty", row.get("qty", line.qty), step=QTY_STEP,
                       label="количество")
        if qty is not None and qty > item.qty:
            raise _bad(f"{where}.qty", f"количество — не больше запрошенного ({item.qty})")
        is_analog = bool(row.get("is_analog", line.is_analog)) and participates
        if is_analog and not req.allow_analogs:
            raise _bad(f"{where}.is_analog", "аналоги в этом тендере не принимаются",
                       code="E-TND-09")
        if not req.allow_partial:
            if not participates:
                raise _bad(f"{where}.participates", "в этом тендере предлагают все позиции",
                           code="E-TND-09")
            if qty is not None and qty < item.qty:
                raise _bad(f"{where}.qty", "в этом тендере предлагают всё количество",
                           code="E-TND-09")
        line.participates, line.price, line.qty, line.is_analog = (
            participates, price, qty, is_analog)
        line.delivery_date = _as_date(f"{where}.delivery_date",
                                      row.get("delivery_date", line.delivery_date))
        line.analog_note = _text(row.get("analog_note", line.analog_note), TEXT_MAX) \
            if is_analog else ""
        line.comment = _text(row.get("comment", line.comment), TEXT_MAX)
        line.save()


def _apply_extras(offer: Offer, tender: Tender, data: dict) -> None:
    """Доставка и СМР — только если тендер их запросил. Сумма дублируется в
    шапку предложения (``delivery_cost``/``works_cost``) для сравнения."""
    requested = _requested_extras(tender)
    for kind, row in (data or {}).items():
        if kind not in requested:
            label = "доставка" if kind == ExtraKind.DELIVERY else "СМР"
            raise _bad(f"extras.{kind}", f"{label} в этом тендере не запрашивалась")
        row = row or {}
        extra, _ = OfferExtra.objects.get_or_create(offer=offer, kind=kind)
        if "amount" in row:
            extra.amount = _decimal(f"extras.{kind}.amount", row["amount"], step=MONEY_STEP,
                                    label="сумма", allow_zero=True)
        if "included_in_price" in row:
            extra.included_in_price = bool(row["included_in_price"])
        if "note" in row:
            extra.note = _text(row["note"], TEXT_MAX)
        extra.save()
        if kind == ExtraKind.DELIVERY:
            offer.delivery_cost, offer.delivery_included = extra.amount, extra.included_in_price
        else:
            offer.works_cost, offer.works_note = extra.amount, extra.note


def _write_scheme(offer: Offer, kind: str, stages: list[dict], postpay_days) -> None:
    PaymentScheme.objects.filter(offer=offer).delete()
    scheme = PaymentScheme.objects.create(offer=offer, kind=kind, postpay_days=postpay_days)
    PaymentStage.objects.bulk_create([PaymentStage(scheme=scheme, **stage) for stage in stages])


def _apply_scheme(offer: Offer, data: dict | None) -> None:
    if data is None:
        PaymentScheme.objects.filter(offer=offer).delete()
        return
    kind = data.get("kind")
    try:
        stages = schemes.from_template(kind, advance_pct=data.get("advance_pct"),
                                       days=data.get("postpay_days"))
    except DomainError as exc:
        for entry in exc.fields:
            entry["field"] = f"payment_scheme.{entry['field']}"
        raise
    _write_scheme(offer, kind, stages,
                  stages[0]["days"] if kind == PaymentKind.POSTPAY else None)


def _apply_requisites(offer: Offer, inv: Invitation, data: dict) -> None:
    """Контрагент БЗО: прислать можно только то же, что в карточке (форма
    возвращает их как есть); потенциальный поставщик вводит сам."""
    if not isinstance(data, dict):
        raise _bad("requisites", "реквизиты — объект")
    current = dict(offer.requisites or {})
    if locked_requisites(inv):
        changed = [key for key, value in data.items() if current.get(key) != value]
        if changed:
            raise _bad("requisites", "реквизиты контрагента меняет закупщик — обратитесь "
                                     "к нему")
        return
    for key, value in data.items():
        if key == "is_vat_payer":
            current[key] = None if value is None else bool(value)
        elif key in REQUISITES:
            current[key] = _text(value if isinstance(value, str) else str(value or ""),
                                 REQUISITES[key])
    offer.requisites = current


# ── переходы ────────────────────────────────────────────────────────────

def _touch(offer: Offer) -> None:
    offer.version += 1
    offer.save()


@transaction.atomic
def save_draft(ctx, data: dict, *, event: Event = _no_event) -> Offer:
    """Сохранить черновик (``PUT offer``): только переданные блоки."""
    tender, inv = _lock(ctx)
    current = _current(inv)
    if current is not None:
        check_version(current, data.get("version"))
    offer = get_draft(inv, tender)
    _apply_header(offer, data)
    if data.get("lines") is not None:
        _apply_lines(offer, tender, data["lines"])
    if data.get("extras") is not None:
        _apply_extras(offer, tender, data["extras"])
    if "payment_scheme" in data:
        _apply_scheme(offer, data["payment_scheme"])
    if data.get("requisites") is not None:
        _apply_requisites(offer, inv, data["requisites"])
    _touch(offer)
    event("offer_saved", {"offer_id": str(offer.pk)})
    return offer


def _check_complete(offer: Offer, tender: Tender, inv: Invitation) -> None:
    lines = list(offer.lines.select_related("item").order_by("item__line_no"))
    taking = [(index, line) for index, line in enumerate(lines) if line.participates]
    if not taking:
        raise _bad("lines", "отметьте хотя бы одну позицию, по которой вы предлагаете цену")
    for index, line in taking:
        if line.price is None:
            raise _bad(f"lines[{index}].price", "укажите цену за единицу")
        if line.qty is None:
            raise _bad(f"lines[{index}].qty", "укажите количество")
    if offer.valid_until is None or offer.valid_until < timezone.localdate():
        raise _bad("valid_until", "срок действия предложения — не раньше сегодняшнего дня")
    for extra in offer.extras.order_by("kind"):
        if extra.amount is None and not extra.included_in_price:
            raise _bad(f"extras.{extra.kind}.amount",
                       "укажите сумму или отметьте «включено в цену»")
    if not locked_requisites(inv) and not (offer.requisites or {}).get("name"):
        raise _bad("requisites.name", "укажите наименование поставщика")


@transaction.atomic
def submit(ctx, data: dict, *, event: Event = _no_event) -> Offer:
    """«Отправить»: согласие на ПДн (при первой отправке; E-TND-08), полнота,
    прежняя отправленная — «Заменено», черновик — версия ``n + 1``,
    приглашение — «Предложение подано»."""
    tender, inv = _lock(ctx)
    offer = _draft(inv)
    if offer is None:
        raise DomainError("E-STS-01", "Нет черновика предложения: внесите изменения и "
                                      "сохраните их перед отправкой.", status=409)
    check_version(offer, data.get("version"))
    if offer.pd_consent_at is None:
        if data.get("pd_consent") is not True:
            raise DomainError(
                "E-TND-08", "Подтвердите согласие на обработку персональных данных.",
                fields=[{"field": "pd_consent", "message": "Нужно согласие"}])
        offer.pd_consent_at = timezone.now()
    _check_complete(offer, tender, inv)
    inv.offers.filter(status=OfferStatus.SUBMITTED).update(
        status=OfferStatus.REPLACED, updated_at=timezone.now())
    last = inv.offers.aggregate(top=Max("number"))["top"] or 0
    offer.status, offer.number, offer.submitted_at = (
        OfferStatus.SUBMITTED, last + 1, timezone.now())
    _touch(offer)
    inv.status = InvitationStatus.SUBMITTED
    inv.save(update_fields=["status", "updated_at"])
    event("offer_submitted", {"offer_id": str(offer.pk), "number": offer.number})
    return offer


@transaction.atomic
def withdraw(ctx, data: dict, *, event: Event = _no_event) -> Offer:
    """Отозвать отправленное предложение; приглашение — «Открыто». Черновик
    (если есть) остаётся — его можно отправить снова до срока."""
    tender, inv = _lock(ctx)
    sent = _submitted(inv)
    if sent is None:
        raise DomainError("E-STS-01", "Отправленного предложения нет — отзывать нечего.",
                          status=409)
    check_version(_current(inv), data.get("version"))
    sent.status = OfferStatus.WITHDRAWN
    _touch(sent)
    inv.status = InvitationStatus.OPENED
    inv.save(update_fields=["status", "updated_at"])
    event("offer_withdrawn", {"offer_id": str(sent.pk), "number": sent.number})
    return sent


@transaction.atomic
def decline(ctx, data: dict, *, event: Event = _no_event) -> Invitation:
    """«Отказаться от участия» с причиной ≥ 10: черновик удаляется,
    отправленная версия — «Отозвано» с причиной, приглашение — «Отказ»."""
    tender, inv = _lock(ctx)
    reason = (data.get("reason") or "").strip()
    if len(reason) < COMMENT_MIN:
        raise _bad("reason", f"опишите причину: не короче {COMMENT_MIN} символов")
    reason = reason[:TEXT_MAX]
    draft = _draft(inv)
    if draft is not None:
        # Черновик ни разу не отправлялся — его файлы уходят физически.
        files.owner_deleted(OFFER_OWNER, draft.pk, actor_id=portal_actor())
        draft.delete()
    sent = _submitted(inv)
    if sent is not None:
        sent.status, sent.declined_reason = OfferStatus.WITHDRAWN, reason
        _touch(sent)
    inv.status = InvitationStatus.DECLINED
    inv.save(update_fields=["status", "updated_at"])
    event("declined", {"reason": reason})
    return inv
