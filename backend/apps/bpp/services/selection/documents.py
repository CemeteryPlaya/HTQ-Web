"""Новый документ по выбранной альтернативе (B5.1; ТЗ §12.4 п.3–4, BR-094,
D-25; решения D-B51-3…D-B51-7, D-B51-11).

``replace_with(offer, source, selector_id=…)`` зовётся в транзакции выбора —
после ``lifecycle.mark_selected`` и перевода исходного документа в «Заменён
альтернативой» (его позиции тем самым свободны: «Заменён» в «Задействовано»
не входит):

- вид нового документа — договор, если исходный договор или АП в KZT больше
  1000 МРП на сегодня (BR-094), иначе счёт без договора;
- автор — автор заявки первой по системному номеру позиции (D-25): черновик
  ждёт его, он прикладывает файл документа контрагента и отправляет;
- контрагент, валюта, НДС, позиции и цены — из АП; полная предоплата у АП —
  признак «аванс» нового счёта (D-11);
- частичная АП — второй черновик по остатку: прочие позиции исходного, его
  контрагент, цены и вид (D-25, Q-E09);
- КП — в новый документ файлом ``alternative_offer`` (тот же файл media
  новой версией 1 у нового владельца, ``files.adopt_media_file``);
- связь АП → документ (``result_type``/``result_id``), ``kpi.
  create_preliminary`` и уведомления автору нового и автору исходного.
"""

from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.bpp.models import (
    AlternativeOffer,
    Invoice,
    PaymentTerms,
    PurchaseRequestItem,
    VatSource,
)
from apps.bpp.models.alternatives import OfferSource
from apps.bpp.services import calc
from apps.bpp.services.actor import Actor
from apps.bpp.services.agreements import agreements as agreement_service
from apps.bpp.services.alternatives import kpi
from apps.bpp.services.core import audit
from apps.bpp.services.core import files as core_files
from apps.bpp.services.invoices import invoices as invoice_service
from apps.bpp.services.money import money
from apps.core.services import ServiceDisabled
from apps.files import interface as files
from apps.notifications import interface as notifications
from htqweb.fallback import fallback
from htqweb.tenancy import current_company_or_none

INVOICE = OfferSource.INVOICE.value
AGREEMENT = OfferSource.AGREEMENT.value
#: Тип файла КП у нового документа (D-B51-7) — тот же код справочника, что у АП.
KP_TYPE = "alternative_offer"
EVENT_NEW_DOCUMENT = "bpp.alternative_new_document"
EVENT_REPLACED = "bpp.alternative_replaced"
_URLS = {INVOICE: "/bpp/invoices/", AGREEMENT: "/bpp/agreements/"}
_LABEL = {INVOICE: "Счёт", AGREEMENT: "Договор"}


def kind_for(offer: AlternativeOffer) -> str:
    """BR-094: договор, если исходный — договор или сумма АП в KZT больше
    1000 МРП на сегодня; иначе счёт без договора."""
    if offer.source_type == AGREEMENT:
        return AGREEMENT
    amount_kzt = offer.amount_kzt if offer.amount_kzt is not None else offer.amount
    return AGREEMENT if money(amount_kzt) > calc.threshold(timezone.localdate()) else INVOICE


def _author(rows: list[PurchaseRequestItem]) -> Actor:
    """D-25: автор заявки первой по системному номеру позиции."""
    first = min(rows, key=lambda row: row.sys_number)
    return Actor.for_user(first.request.author_id, company=current_company_or_none())


def _purchase_kind(source) -> str:
    return (source.purchase_type if isinstance(source, Invoice) else source.agreement_type) or ""


def _invoice_draft(author: Actor, rows, quantities, amounts, *, counterparty, currency_code,
                   with_vat, vat_rate, vat_source, advance: bool) -> Invoice:
    inv = invoice_service.new_invoice(author, rows=rows, agreement=None,
                                      quantities=quantities, amounts=amounts)
    inv.counterparty, inv.currency_code, inv.with_vat = counterparty, currency_code, with_vat
    if with_vat and vat_source == VatSource.MANUAL and vat_rate is not None:
        inv.vat_rate, inv.vat_source = vat_rate, VatSource.MANUAL
    inv.is_advance = advance
    invoice_service.recalc(inv)
    inv.save()
    return inv


def _agreement_draft(author: Actor, rows, quantities, amounts, *, project_id, article_id,
                     kind: str, counterparty, currency_code, with_vat, vat_rate, vat_source):
    agr = agreement_service.new_agreement(
        author, rows=rows, project_id=project_id, article_id=article_id, kind=kind,
        quantities=quantities, amounts=amounts)
    agr.counterparty, agr.currency_code, agr.with_vat = counterparty, currency_code, with_vat
    if with_vat and vat_source == VatSource.MANUAL and vat_rate is not None:
        agr.vat_rate, agr.vat_source = vat_rate, VatSource.MANUAL
    agreement_service.recalc_vat(agr)
    agr.save()
    return agr


def _draft(kind: str, author: Actor, lines: list[tuple[PurchaseRequestItem, Decimal, Decimal]],
           source, *, counterparty, currency_code, with_vat, vat_rate, vat_source,
           advance: bool):
    rows = [row for row, _, _ in lines]
    quantities = {str(row.pk): qty for row, qty, _ in lines}
    amounts = {str(row.pk): money(amount) for row, _, amount in lines}
    common = dict(counterparty=counterparty, currency_code=currency_code, with_vat=with_vat,
                  vat_rate=vat_rate, vat_source=vat_source)
    if kind == INVOICE:
        return _invoice_draft(author, rows, quantities, amounts, advance=advance, **common)
    return _agreement_draft(author, rows, quantities, amounts, project_id=source.project_id,
                            article_id=source.article_id, kind=_purchase_kind(source),
                            **common)


def _source_lines(source) -> list[tuple[str, PurchaseRequestItem, Decimal, Decimal]]:
    """Позиции исходного: ``(id строки, позиция заявки, кол-во, сумма)``. Сумма
    позиции договора без своей суммы — сумма позиции заявки (как у АП)."""
    if isinstance(source, Invoice):
        rows = source.lines.select_related("request_item__request").order_by("created_at")
        return [(str(row.pk), row.request_item, row.qty, row.amount) for row in rows]
    rows = source.items.select_related("request_item__request").order_by("created_at")
    return [(str(row.pk), row.request_item, row.qty,
             row.amount if row.amount is not None else row.request_item.amount) for row in rows]


def _copy_kp(offer: AlternativeOffer, doc, actor_id: int) -> int:
    """КП альтернативы — в новый документ (тот же файл media, версия 1)."""
    owner = core_files.owner_type_of(doc)
    copied = 0
    for version in files.current_files("bpp.alternative_offer", offer.pk, KP_TYPE):
        files.adopt_media_file(owner, doc.pk, file_type=KP_TYPE,
                               media_file_id=version["media_file_id"],
                               uploaded_by_id=actor_id)
        copied += 1
    return copied


def _notify(recipients: set[int], *, event: str, title: str, url: str, doc,
            actor_id: int) -> None:
    """Центр уведомлений под своей точкой сохранения: сбой не роняет выбор,
    но и не глотается молча (как ``lifecycle._notify``)."""
    recipients.discard(actor_id)
    company = current_company_or_none()
    if not recipients or company is None:
        return
    try:
        with transaction.atomic():
            notifications.notify(recipients=sorted(recipients), event=event, title=title,
                                 url=url, company_slug=company,
                                 target_type=doc._meta.label_lower, target_id=str(doc.pk),
                                 actor_id=actor_id, deliver=True)
    except ServiceDisabled as exc:
        fallback("bpp.selection.notify_disabled", None, expected=True, exc=exc,
                 reason="центр уведомлений выключен — о новом документе не уведомлены",
                 document=str(doc.pk))
    except Exception as exc:
        fallback("bpp.selection.notify_failed", None, exc=exc,
                 reason="уведомление о новом документе по альтернативе не записано",
                 document=str(doc.pk))


def replace_with(offer: AlternativeOffer, source, *, selector_id: int) -> dict:
    """Черновик(и) нового документа по выбранной АП; ``{"result_type",
    "result", "remainder", "kpi"}``. Исходный уже «Заменён альтернативой»,
    АП — «Выбрано»."""
    lines = list(offer.lines.select_related("request_item__request")
                 .order_by("request_item__sys_number"))
    kind = kind_for(offer)
    author = _author([line.request_item for line in lines])
    result = _draft(
        kind, author, [(line.request_item, line.qty, line.amount) for line in lines], source,
        counterparty=offer.counterparty, currency_code=offer.currency_code,
        with_vat=offer.with_vat, vat_rate=offer.vat_rate, vat_source=offer.vat_source,
        advance=offer.payment_terms == PaymentTerms.FULL_PREPAY)

    covered = {str(line.source_line_id) for line in lines}
    rest = [(row, qty, amount) for key, row, qty, amount in _source_lines(source)
            if key not in covered]
    source_kind = INVOICE if isinstance(source, Invoice) else AGREEMENT
    remainder = _draft(
        source_kind, author, rest, source, counterparty=source.counterparty,
        currency_code=source.currency_code, with_vat=source.with_vat,
        vat_rate=source.vat_rate, vat_source=source.vat_source,
        advance=getattr(source, "is_advance", False)) if rest else None

    offer.result_type, offer.result_id = kind, result.pk
    offer.save(update_fields=["result_type", "result_id", "updated_at"])
    kp = _copy_kp(offer, result, selector_id)
    record = kpi.create_preliminary(offer.pk, result_type=kind, result_id=result.pk,
                                    selected_by_id=selector_id)

    audit.record(result, "created_from_alternative", actor_id=selector_id, changes={
        "offer": offer.number, "source": source.number, "kp_files": kp})
    if remainder is not None:
        audit.record(remainder, "created_from_remainder", actor_id=selector_id, changes={
            "offer": offer.number, "source": source.number})
    audit.record(source, "replaced", actor_id=selector_id, changes={
        "offer": offer.number, "result": result.number,
        "remainder": remainder.number if remainder is not None else None})

    created = result.number + (f" и {remainder.number} (по остатку)" if remainder else "")
    _notify({author.user_id}, event=EVENT_NEW_DOCUMENT, doc=result, actor_id=selector_id,
            url=f"{_URLS[kind]}{result.pk}",
            title=f"{_LABEL[kind]} {result.number} по альтернативе {offer.number} ждёт вас: "
                  f"приложите документ контрагента и отправьте")
    _notify({source.author_id}, event=EVENT_REPLACED, doc=source, actor_id=selector_id,
            url=f"{_URLS[offer.source_type]}{source.pk}",
            title=f"{source.number} заменён альтернативой {offer.number}: создан {created}")
    return {"result_type": kind, "result": result, "remainder": remainder, "kpi": record}
