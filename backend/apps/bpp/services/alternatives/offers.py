"""Альтернативное предложение (АП): черновик, подача, отзыв, лимиты (ТЗ §12.1,
§12.3, §12.7, BR-090…092; план этапа 5 A, задача 2).

Исходный документ — счёт без договора в «На рассмотрении ФД» или договор «На
согласовании» (окно подачи, BR-090). ``source_type``/``source_id`` — ссылка
без FK; строки исходного документа читаются напрямую (внутри ``bpp`` подмодуль
вправе), поля счёта и договора не пишутся, кроме ``alt_limit``
(``set_limit``, D-S5-2).

**Порядок блокировок** (Review Focus 1, 2): сначала строка исходного
документа (``select_for_update``), затем строки АП — так же, как у решения ФД
(``invoices.lock``), поэтому подача и решение сериализуются, а два СН, делящие
последнее место в лимите, — тоже. Лимиты, окно подачи и уникальность
контрагента проверяются под этой блокировкой. Модуль сам не импортирует
сервисы счёта и договора (``invoices``, ``agreements``): их хуки зовут
``alternatives.lifecycle`` (задача 3), и импорт в обратную сторону дал бы цикл.

Деньги — ``Decimal``, ``ROUND_HALF_UP``; значение вне диапазона столбца — 422
``E-VAL-01`` на поле, а не ошибка БД. Цена — за единицу, с НДС, если он есть
(D-S5-3); суммы в KZT — на дату правки/подачи (D-S5-4).
"""

from __future__ import annotations

import re
import uuid
from decimal import Decimal, InvalidOperation

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.access import interface as access
from apps.bpp.models import (
    Agreement,
    AgreementStatus,
    AlternativeOffer,
    AlternativeOfferLine,
    Invoice,
    InvoiceBasis,
    InvoiceStatus,
    OfferStatus,
)
from apps.bpp.models.alternatives import LIVE_OFFER_STATUSES, OfferSource, PaymentTerms
from apps.bpp.models.requests import InitiatorRole
from apps.bpp.services import calc
from apps.bpp.services.actor import ROLE_GROUP, Actor
from apps.bpp.services.alternatives import calc as offer_calc
from apps.bpp.services.core import audit
from apps.bpp.services.core import files as core_files
from apps.bpp.services.core.errors import check_version
from apps.bpp.services.core.numbering import next_number
from apps.bpp.services.counterparties import lookup as counterparties
from apps.bpp.services.money import fmt, money
from apps.core.services import ServiceDisabled
from apps.notifications import interface as notifications
from htqweb.errors import DomainError
from htqweb.fallback import fallback
from htqweb.tenancy import current_company_or_none

__all__ = [
    "allowed_actions", "can_view", "create", "delete_draft", "get_visible", "serialize",
    "set_limit", "source_of", "submit", "update_draft", "window_open", "withdraw",
]

NODE = "bpp.alternatives"
SOURCE_INVOICE = OfferSource.INVOICE.value
SOURCE_AGREEMENT = OfferSource.AGREEMENT.value
_MODELS = {SOURCE_INVOICE: Invoice, SOURCE_AGREEMENT: Agreement}
_URLS = {SOURCE_INVOICE: "/bpp/invoices/", SOURCE_AGREEMENT: "/bpp/agreements/"}

#: Потолок ``alt_limit`` (ТЗ §12.1, Q-E10) и лимит АП одного автора на документ (D-S5-2).
LIMIT_MAX = 10
AUTHOR_LIMIT = {InitiatorRole.SN.value: 1, InitiatorRole.PM.value: 3}
JUSTIFICATION_MIN, JUSTIFICATION_MAX = 10, 2000
JUSTIFICATION_MORE_EXPENSIVE_MIN = 30
NOTE_MAX = 2000
EVENT_SUBMITTED = "bpp.alternative_submitted"

#: Столбцы ``Decimal(18,2)`` держат меньше 10^16; процент — ``Decimal(12,2)``.
MONEY_LIMIT = Decimal(10) ** 16
PCT_LIMIT = Decimal(10) ** 10
_CURRENCY = re.compile(r"^[A-Z]{3}$")

FIELD_LABELS = {
    "counterparty_id": "Контрагент",
    "lines": "Цены позиций",
    "delivery_date": "Срок поставки",
    "payment_terms": "Условия оплаты",
    "justification": "Обоснование",
    "files": "Коммерческое предложение",
}


# ── ошибки ──────────────────────────────────────────────────────────────

def _deny(text: str) -> DomainError:
    return DomainError("E-ACC-01", f"{text} Если это ошибка, обратитесь к администратору.",
                       status=403)


def _bad(field: str, message: str, code: str = "E-VAL-01") -> DomainError:
    return DomainError(code, message, fields=[{"field": field, "message": message}])


def _not_found(text: str = "Альтернатива не найдена.") -> DomainError:
    return DomainError("E-NOT-FOUND", text, status=404)


def _window_closed() -> DomainError:
    return DomainError("E-STATE-01", "Документ уже решён — альтернатива не подаётся",
                       fields=[{"field": "source_id", "message": "Окно подачи закрыто"}])


def _state_error(action: str, offer: AlternativeOffer) -> DomainError:
    return DomainError(
        "E-STS-01", f"Нельзя {action} альтернативу {offer.number} в статусе "
                    f"„{offer.get_status_display()}“.", status=409)


def _range(field: str) -> DomainError:
    return _bad(field, "Сумма вне допустимого диапазона: уменьшите цену или число позиций.")


def _key(value) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None


# ── исходный документ ───────────────────────────────────────────────────

def source_of(source_type: str, source_id, *, lock: bool = False) -> Invoice | Agreement:
    """Исходный документ; неизвестный вид или нет такого — 404. ``lock`` —
    ``select_for_update`` (в транзакции), первый замок подачи и отзыва."""
    model = _MODELS.get(source_type)
    key = _key(source_id)
    if model is None or key is None:
        raise _not_found("Документ не найден.")
    rows = model.objects.select_for_update() if lock else model.objects
    source = rows.filter(pk=key).first()
    if source is None:
        raise _not_found("Документ не найден.")
    return source


def source_kind(source) -> str:
    return SOURCE_INVOICE if isinstance(source, Invoice) else SOURCE_AGREEMENT


def window_open(source) -> bool:
    """BR-090: АП подают, пока счёт без договора «На рассмотрении ФД» (решение
    ФД уводит его из этого статуса) или идёт согласование договора.
    ``fd_decided_at`` не смотрим: после возврата и повторной отправки он
    остаётся от прошлого решения, а окно открыто снова (§12.4 п.7)."""
    if isinstance(source, Invoice):
        return (source.basis == InvoiceBasis.NO_CONTRACT
                and source.status == InvoiceStatus.UNDER_REVIEW)
    return source.status == AgreementStatus.ON_REVIEW


def _check_kind(source) -> None:
    """Документы, к которым АП не подаётся вовсе (не «окно закрыто»)."""
    if isinstance(source, Invoice):
        if source.basis == InvoiceBasis.CONTRACT:
            raise _bad("source_id", "Альтернатива к счёту по договору не подаётся")
        return
    if source.is_open:
        raise _bad("source_id", "К открытому договору альтернатива не подаётся: "
                                "у позиций нет цен")
    if source.parent_agreement_id is not None:
        raise _bad("source_id", "К допсоглашению альтернатива не подаётся")


def _source_lines(source) -> dict[str, dict]:
    """Позиции исходного документа: ``{id строки: {qty, amount, request_item_id}}``.
    Сумма позиции договора без своей суммы — сумма позиции заявки."""
    if isinstance(source, Invoice):
        return {str(row.pk): {"qty": row.qty, "amount": row.amount,
                              "request_item_id": row.request_item_id}
                for row in source.lines.order_by("created_at")}
    return {str(row.pk): {"qty": row.qty,
                          "amount": row.amount if row.amount is not None
                          else row.request_item.amount,
                          "request_item_id": row.request_item_id}
            for row in source.items.select_related("request_item").order_by("created_at")}


def _source_part_kzt(source, amount: Decimal) -> Decimal | None:
    """Исходная часть в KZT по курсу исходного документа (D-S5-4): счёт — по
    его ``rate``, договор — курс НБРК на его дату или сегодня. Курса нет —
    ``None`` (подача отклонит ``E-REF-05``)."""
    try:
        if source.currency_code == calc.KZT:
            return money(amount)
        if isinstance(source, Invoice):
            if not source.rate:
                return None
            raw = amount * source.rate
            return money(raw) if abs(raw) < MONEY_LIMIT else None
        on_date = source.ext_date or timezone.localdate()
        value = calc.to_kzt(amount, source.currency_code, on_date).amount_kzt
    except (DomainError, InvalidOperation):
        return None
    return value if abs(value) < MONEY_LIMIT else None


# ── права и видимость ───────────────────────────────────────────────────

def can_view(actor: Actor, offer: AlternativeOffer) -> bool:
    """Одно правило на карточку, журнал и КП — ``read.can_view`` (задача 4):
    автор; черновик — только он; поданную — ФД, ТД, ОД, ГД и автор
    исходного документа. ``read`` импортирует этот модуль — отсюда импорт
    в функции."""
    from apps.bpp.services.alternatives import read

    return read.can_view(actor, offer)


def get_visible(actor: Actor, offer_id) -> AlternativeOffer:
    key = _key(offer_id)
    offer = AlternativeOffer.objects.filter(pk=key).first() if key else None
    if offer is None or not can_view(actor, offer):
        raise _not_found()
    return offer


def _author_role(actor: Actor) -> str:
    """Роль автора — по группе статей, как ``Actor.initiator_roles`` (матрица
    27.09: у СН ``bpp.articles.supply``, у ПМ — ``bpp.articles.pm``; ФД и
    прочие видят обе, но ``bpp.alternatives`` create не имеют). Создаёт АП
    только держатель create, и он СН, пока у него нет одной лишь группы
    ПМ: без групп вовсе — тоже СН (лимит строже, а не мягче)."""
    groups = actor.group_codes
    if ROLE_GROUP[InitiatorRole.PM] in groups and ROLE_GROUP[InitiatorRole.SN] not in groups:
        return InitiatorRole.PM.value
    return InitiatorRole.SN.value


def _require_create(actor: Actor) -> None:
    """Право подавать АП проверяется на каждом шаге до подачи, а не только
    при создании: снабженец, у которого роль сняли, свой черновик уже не
    правит и не подаёт. Удалить черновик и отозвать поданную — может."""
    if not actor.can(NODE, "create"):
        raise _deny("Альтернативные предложения подают снабженцы.")


def _require_author(actor: Actor, offer: AlternativeOffer, action: str) -> None:
    if offer.author_id != actor.user_id:
        raise _deny(f"«{action}» доступно только автору альтернативы {offer.number}.")


def allowed_actions(actor: Actor, offer: AlternativeOffer) -> list[str]:
    if offer.author_id != actor.user_id:
        return []
    if offer.status == OfferStatus.DRAFT:
        return ["save", "submit", "delete"] if actor.can(NODE, "create") else ["delete"]
    if offer.status == OfferStatus.SUBMITTED:
        source = _MODELS[offer.source_type].objects.filter(pk=offer.source_id).first()
        if source is not None and window_open(source):
            return ["withdraw"]
    return []


# ── блокировки и лимиты ─────────────────────────────────────────────────

def _locked(offer_id) -> tuple[Invoice | Agreement, AlternativeOffer]:
    """Исходный документ под замком, затем АП под замком (Review Focus 1, 2)."""
    key = _key(offer_id)
    probe = AlternativeOffer.objects.filter(pk=key).first() if key else None
    if probe is None:
        raise _not_found()
    source = source_of(probe.source_type, probe.source_id, lock=True)
    offer = AlternativeOffer.objects.select_for_update().filter(pk=probe.pk).first()
    if offer is None:
        raise _not_found()
    return source, offer


def _counts(source, *, exclude_id=None) -> dict:
    rows = AlternativeOffer.objects.filter(source_type=source_kind(source), source_id=source.pk)
    if exclude_id is not None:
        rows = rows.exclude(pk=exclude_id)
    return {status: rows.filter(status=status).count()
            for status in (OfferStatus.SUBMITTED, OfferStatus.SELECTED)}


def _decided_count(source, *, exclude_id=None) -> int:
    counts = _counts(source, exclude_id=exclude_id)
    return counts[OfferStatus.SUBMITTED] + counts[OfferStatus.SELECTED]


def _check_document_limit(source, *, exclude_id=None) -> None:
    filed = _decided_count(source, exclude_id=exclude_id)
    if filed >= source.alt_limit:
        raise _bad("source_id", f"К документу уже подано {filed} альтернатив — это лимит")


def _check_author_limit(source, author_id: int, role: str, *, exclude_id=None) -> None:
    others = AlternativeOffer.objects.filter(
        source_type=source_kind(source), source_id=source.pk, author_id=author_id,
        status__in=[s.value for s in LIVE_OFFER_STATUSES])
    if exclude_id is not None:
        others = others.exclude(pk=exclude_id)
    limit = AUTHOR_LIMIT[role]
    if others.count() >= limit:
        text = ("У вас уже есть альтернатива к этому документу — снабженец подаёт одну"
                if limit == 1 else
                f"Вы уже подали {limit} альтернативы к этому документу — это лимит")
        raise _bad("source_id", text)


# ── расчёт ──────────────────────────────────────────────────────────────

def _price(value, *, field: str = "lines") -> Decimal:
    try:
        price = Decimal(str(value))
    except InvalidOperation:
        raise _bad(field, "Цена — число больше нуля.") from None
    if not price.is_finite() or price <= 0:
        raise _bad(field, "Цена позиции — больше нуля.")
    if price >= MONEY_LIMIT:
        raise _range(field)
    price = money(price)
    if price <= 0:
        raise _bad(field, "Цена позиции — больше нуля.")
    return price


def _line_amount(qty: Decimal, price: Decimal) -> Decimal:
    if qty * price >= MONEY_LIMIT:
        raise _range("lines")
    return offer_calc.offer_amount([(qty, price)])


def _in_range(value: Decimal | None, field: str) -> None:
    if value is not None and abs(value) >= MONEY_LIMIT:
        raise _range(field)


def _recalc(offer: AlternativeOffer, source, lines: list[AlternativeOfferLine],
            *, strict: bool = False) -> None:
    """НДС, суммы строк, ``amount``, ``rate``/``amount_kzt``, ``source_amount_kzt``
    и экономия (CALC-013). ``strict`` — при подаче: нет курса — ``E-REF-05``.
    Экономия — только когда каждая позиция с ценой: недооценённая АП дешевле
    исходного мнимо."""
    today = timezone.localdate()
    counterparty = offer.counterparty
    if not offer.with_vat:
        offer.vat_rate, offer.vat_source = None, ""
    elif counterparty is not None and offer.vat_source != "manual":
        pick = calc.vat_for(counterparty.country_code, today)
        offer.vat_rate, offer.vat_source = pick.rate, pick.source
    pairs = []
    for line in lines:
        if line.price is None:
            line.amount = None
        else:
            line.amount = _line_amount(line.qty, line.price)
            pairs.append((line.qty, line.price))
    offer.amount = offer_calc.offer_amount(pairs)
    _in_range(offer.amount, "lines")
    offer.vat_amount = (calc.vat_amount(offer.amount, offer.vat_rate)
                        if offer.with_vat and offer.vat_rate is not None else None)
    try:
        converted = calc.to_kzt(offer.amount, offer.currency_code, today)
        offer.rate, offer.amount_kzt = converted.rate, converted.amount_kzt
    except DomainError:
        if strict:
            raise
        offer.rate, offer.amount_kzt = None, None
    except InvalidOperation:
        raise _range("lines") from None
    _in_range(offer.amount_kzt, "lines")

    source_lines = _source_lines(source)
    part = offer_calc.source_part(
        [(source_lines[str(line.source_line_id)]["qty"],
          source_lines[str(line.source_line_id)]["amount"]) for line in lines])
    offer.source_amount_kzt = _source_part_kzt(source, part)
    offer.saving_amount = offer.saving_pct = None
    if (offer.amount_kzt is not None and offer.source_amount_kzt is not None
            and lines and all(line.price is not None for line in lines)):
        offer.saving_amount, offer.saving_pct = offer_calc.saving(
            offer.source_amount_kzt, offer.amount_kzt)
        _in_range(offer.saving_amount, "lines")
        if abs(offer.saving_pct) >= PCT_LIMIT:
            raise _range("lines")


def _snapshot(offer: AlternativeOffer) -> dict:
    def text(value):
        return None if value is None else str(value)
    return {
        "counterparty_id": text(offer.counterparty_id), "currency_code": offer.currency_code,
        "amount": text(offer.amount), "amount_kzt": text(offer.amount_kzt),
        "with_vat": offer.with_vat, "vat_rate": text(offer.vat_rate),
        "vat_source": offer.vat_source, "source_amount_kzt": text(offer.source_amount_kzt),
        "saving_amount": text(offer.saving_amount), "saving_pct": text(offer.saving_pct),
        "delivery_date": offer.delivery_date.isoformat() if offer.delivery_date else None,
        "payment_terms": offer.payment_terms, "payment_terms_note": offer.payment_terms_note,
        "justification": offer.justification, "status": offer.status,
        "lines": [{"source_line_id": str(line.source_line_id), "price": text(line.price)}
                  for line in offer.lines.order_by("created_at")],
    }


def _touch(offer: AlternativeOffer, actor_id: int | None) -> None:
    offer.version += 1
    offer.updated_by = actor_id
    offer.save()


# ── создание ────────────────────────────────────────────────────────────

@transaction.atomic
def create(actor: Actor, *, source_type: str, source_id) -> AlternativeOffer:
    _require_create(actor)
    source = source_of(source_type, source_id, lock=True)
    if not actor.sees_project(source.project_id):
        raise _not_found("Документ не найден.")
    _check_kind(source)
    if not window_open(source):
        raise _window_closed()
    role = _author_role(actor)
    _check_document_limit(source)
    _check_author_limit(source, actor.user_id, role)
    source_lines = _source_lines(source)
    if not source_lines:
        raise _bad("source_id", "В исходном документе нет позиций для альтернативы.")
    offer = AlternativeOffer(
        number=next_number("АП"), source_type=source_kind(source), source_id=source.pk,
        project_id=source.project_id, article_id=source.article_id, author_id=actor.user_id,
        author_role=role, own_document=actor.user_id == source.author_id,
        currency_code=source.currency_code, created_by=actor.user_id, updated_by=actor.user_id)
    lines = [AlternativeOfferLine(
        offer=offer, source_line_id=uuid.UUID(key), request_item_id=row["request_item_id"],
        qty=row["qty"], source_price=offer_calc.source_price(row["amount"], row["qty"]),
        created_by=actor.user_id, updated_by=actor.user_id)
        for key, row in source_lines.items()]
    _recalc(offer, source, lines)
    offer.save()
    for line in lines:
        line.offer = offer
        line.save()
    audit.record(offer, "created", actor_id=actor.user_id, changes={
        "source": {"type": offer.source_type, "id": str(source.pk), "number": source.number},
        "own_document": offer.own_document, "author_role": role})
    return offer


# ── правка черновика ────────────────────────────────────────────────────

def _apply_counterparty(offer: AlternativeOffer, source, counterparty_id) -> None:
    if not counterparty_id:
        offer.counterparty = None
        return
    counterparty = counterparties.assert_usable(counterparty_id)
    duplicate = source.counterparty_id == counterparty.pk or AlternativeOffer.objects.filter(
        source_type=offer.source_type, source_id=offer.source_id, counterparty=counterparty,
        status__in=[s.value for s in LIVE_OFFER_STATUSES]).exclude(pk=offer.pk).exists()
    if duplicate:
        raise _bad("counterparty_id", "Контрагент совпадает с исходным или с другой "
                                      "альтернативой по документу")
    offer.counterparty = counterparty


def _apply_lines(offer: AlternativeOffer, source, rows: list[dict], actor_id: int) -> None:
    if not rows:
        raise _bad("lines", "В альтернативе — минимум одна позиция.")
    source_lines = _source_lines(source)
    current = {str(line.source_line_id): line for line in offer.lines.all()}
    keep: dict[str, Decimal | None] = {}
    for row in rows:
        key = str(row["source_line_id"])
        if key not in source_lines:
            raise _bad("lines", "Неизвестная позиция исходного документа.")
        if key in keep:
            raise _bad("lines", "Позиция указана дважды.")
        keep[key] = None if row.get("price") is None else _price(row["price"])
    offer.lines.exclude(source_line_id__in=[uuid.UUID(key) for key in keep]).delete()
    for key, price in keep.items():
        line = current.get(key)
        if line is None:
            src = source_lines[key]
            line = AlternativeOfferLine(
                offer=offer, source_line_id=uuid.UUID(key),
                request_item_id=src["request_item_id"], qty=src["qty"],
                source_price=offer_calc.source_price(src["amount"], src["qty"]),
                created_by=actor_id)
        line.price, line.updated_by = price, actor_id
        line.save()


def _apply_header(offer: AlternativeOffer, data: dict) -> None:
    if "currency_code" in data:
        code = str(data["currency_code"] or "").strip().upper()
        if not _CURRENCY.match(code):
            raise _bad("currency_code", "Валюта — трёхбуквенный код, например KZT.")
        offer.currency_code = code
    if "delivery_date" in data:
        when = data["delivery_date"]
        if when is not None and when < timezone.localdate():
            raise _bad("delivery_date", "Срок поставки — не раньше сегодняшней даты.")
        offer.delivery_date = when
    if "payment_terms" in data:
        terms = data["payment_terms"] or ""
        if terms not in ("", *PaymentTerms.values):
            raise _bad("payment_terms", "Неизвестные условия оплаты.")
        offer.payment_terms = terms
    if "payment_terms_note" in data:
        note = (data["payment_terms_note"] or "").strip()
        if len(note) > NOTE_MAX:
            raise _bad("payment_terms_note", f"Не длиннее {NOTE_MAX} символов.")
        offer.payment_terms_note = note
    if "justification" in data:
        text = (data["justification"] or "").strip()
        if text and not JUSTIFICATION_MIN <= len(text) <= JUSTIFICATION_MAX:
            raise _bad("justification", f"Обоснование — от {JUSTIFICATION_MIN} до "
                                        f"{JUSTIFICATION_MAX} символов.")
        offer.justification = text
    if "with_vat" in data and data["with_vat"] is not None:
        offer.with_vat = bool(data["with_vat"])
    if "vat_rate" in data:
        if data["vat_rate"] is None:
            offer.vat_source = ""
        else:
            rate = Decimal(str(data["vat_rate"]))
            if not rate.is_finite() or not 0 <= rate <= 100:
                raise _bad("vat_rate", "Ставка НДС — от 0 до 100 %.")
            offer.vat_rate, offer.vat_source = rate.quantize(Decimal("0.01")), "manual"


@transaction.atomic
def update_draft(actor: Actor, offer_id, *, expected_version: int | None,
                 data: dict) -> AlternativeOffer:
    _require_create(actor)
    source, offer = _locked(offer_id)
    _require_author(actor, offer, "Изменить")
    if offer.status != OfferStatus.DRAFT:
        raise _state_error("изменить", offer)
    check_version(offer, expected_version)
    before = _snapshot(offer)
    if "counterparty_id" in data:
        _apply_counterparty(offer, source, data["counterparty_id"])
        if offer.counterparty is not None and "with_vat" not in data:
            offer.with_vat = offer.counterparty.is_vat_payer
    _apply_header(offer, data)
    if "lines" in data and data["lines"] is not None:
        _apply_lines(offer, source, data["lines"], actor.user_id)
    lines = list(offer.lines.order_by("created_at"))
    _recalc(offer, source, lines)
    try:
        with transaction.atomic():
            for line in lines:
                line.save(update_fields=["amount", "updated_at"])
            _touch(offer, actor.user_id)
    except IntegrityError:
        # Частичный индекс BR-091 — страховка, если проверка выше не сработала.
        raise _bad("counterparty_id", "Контрагент совпадает с исходным или с другой "
                                      "альтернативой по документу") from None
    audit.record(offer, "updated", actor_id=actor.user_id,
                 changes={"before": before, "after": _snapshot(offer)})
    return offer


@transaction.atomic
def delete_draft(actor: Actor, offer_id, *, expected_version: int | None) -> None:
    _, offer = _locked(offer_id)
    _require_author(actor, offer, "Удалить")
    if offer.status != OfferStatus.DRAFT:
        raise _state_error("удалить", offer)
    check_version(offer, expected_version)
    audit.record(offer, "deleted", actor_id=actor.user_id, changes={"number": offer.number})
    core_files.owner_deleted(offer, actor_id=actor.user_id)
    offer.delete()


# ── подача и отзыв ──────────────────────────────────────────────────────

def _check_required(offer: AlternativeOffer, lines: list[AlternativeOfferLine]) -> None:
    missing = []
    if not offer.counterparty_id:
        missing.append("counterparty_id")
    if not lines or any(line.price is None for line in lines):
        missing.append("lines")
    if not offer.delivery_date:
        missing.append("delivery_date")
    if not offer.payment_terms:
        missing.append("payment_terms")
    if len(offer.justification.strip()) < JUSTIFICATION_MIN:
        missing.append("justification")
    if not core_files.list_files(offer):
        missing.append("files")
    if missing:
        names = ", ".join(f"„{FIELD_LABELS[key]}“" for key in missing)
        raise DomainError(
            "E-VAL-01", f"Не удалось подать альтернативу. Не заполнено: {names}. "
                        f"Заполните поля и повторите подачу.",
            fields=[{"field": key, "message": "Обязательное поле"} for key in missing])


def _pct_text(value: Decimal) -> str:
    return format(value.normalize(), "f").replace(".", ",")


def _notify_submitted(offer: AlternativeOffer, source, *, actor_id: int) -> None:
    """ФД и автору исходного документа (ТЗ §12.7). Запись — под своей точкой
    сохранения: сбой центра подачу не роняет, но и не глотается молча."""
    company = current_company_or_none()
    if company is None:
        fallback("bpp.alternatives.submitted_notify_no_company", None, expected=True,
                 reason="нет контекста компании — ФД и автор документа не уведомлены",
                 offer=str(offer.pk))
        return
    try:
        recipients = set(access.holders_of("bpp.invoices.decision", "edit", company))
        recipients.add(source.author_id)
        recipients.discard(actor_id)
        if not recipients:
            return
        saving, pct = offer.saving_amount, offer.saving_pct
        effect = (f"экономия {fmt(saving)} ({_pct_text(pct)} %)" if saving >= 0
                  else f"удорожание {fmt(-saving)} ({_pct_text(-pct)} %)")
        title = f"Подана альтернатива {offer.number} к {source.number}: {effect}"
        with transaction.atomic():
            notifications.notify(
                recipients=sorted(recipients), event=EVENT_SUBMITTED, title=title,
                url=f"{_URLS[offer.source_type]}{source.pk}", company_slug=company,
                target_type=offer._meta.label_lower, target_id=str(offer.pk),
                actor_id=actor_id, deliver=True)
    except ServiceDisabled as exc:
        fallback("bpp.alternatives.submitted_notify_disabled", None, expected=True, exc=exc,
                 reason="центр уведомлений выключен — ФД и автор документа не уведомлены",
                 offer=str(offer.pk))
    except Exception as exc:
        fallback("bpp.alternatives.submitted_notify_failed", None, exc=exc,
                 reason="центр уведомлений не принял уведомление о поданной альтернативе",
                 offer=str(offer.pk))


@transaction.atomic
def submit(actor: Actor, offer_id, *, expected_version: int | None) -> AlternativeOffer:
    _require_create(actor)
    source, offer = _locked(offer_id)
    _require_author(actor, offer, "Подать")
    # Окно — до статуса: черновик к решённому документу уже закрыт
    # (``lifecycle.close_for_source``), и причина для автора — решение.
    if not window_open(source):
        raise _window_closed()
    if offer.status != OfferStatus.DRAFT:
        raise _state_error("подать", offer)
    check_version(offer, expected_version)
    _check_document_limit(source, exclude_id=offer.pk)
    _check_author_limit(source, offer.author_id, offer.author_role, exclude_id=offer.pk)
    lines = list(offer.lines.order_by("created_at"))
    _check_required(offer, lines)
    # Между черновиком и подачей контрагента могли заблокировать, а другая
    # АП — занять; и то и другое — под замком исходного документа.
    _apply_counterparty(offer, source, offer.counterparty_id)
    if offer.delivery_date < timezone.localdate():
        raise _bad("delivery_date", "Срок поставки — не раньше сегодняшней даты.")
    _recalc(offer, source, lines, strict=True)
    if offer.source_amount_kzt is None:
        raise DomainError(
            "E-REF-05", f"Нет курса {source.currency_code} для исходного документа "
                        f"{source.number}: сумму в тенге посчитать нельзя. Финансовый "
                        f"директор может внести курс в справочнике валют.",
            fields=[{"field": "source_id", "message": "Нет курса исходного документа"}])
    if offer.saving_amount < 0 and len(offer.justification.strip()) \
            < JUSTIFICATION_MORE_EXPENSIVE_MIN:
        raise _bad("justification", "Альтернатива дороже исходного — опишите причину "
                                    "(сроки, качество, наличие), не короче 30 символов")
    for line in lines:
        line.save(update_fields=["amount", "updated_at"])
    offer.status, offer.submitted_at = OfferStatus.SUBMITTED, timezone.now()
    _touch(offer, actor.user_id)
    audit.record(offer, "submitted", actor_id=actor.user_id, changes=_snapshot(offer))
    _notify_submitted(offer, source, actor_id=actor.user_id)
    return offer


@transaction.atomic
def withdraw(actor: Actor, offer_id, *, expected_version: int | None) -> AlternativeOffer:
    source, offer = _locked(offer_id)
    _require_author(actor, offer, "Отозвать")
    if not window_open(source):
        raise DomainError("E-STATE-01", "Документ уже решён — альтернативу не отозвать",
                          status=422)
    if offer.status != OfferStatus.SUBMITTED:
        raise _state_error("отозвать", offer)
    check_version(offer, expected_version)
    offer.status = OfferStatus.WITHDRAWN
    _touch(offer, actor.user_id)
    audit.record(offer, "withdrawn", actor_id=actor.user_id, changes={"number": offer.number})
    return offer


# ── лимит на документ ───────────────────────────────────────────────────

@transaction.atomic
def set_limit(actor: Actor, *, source_type: str, source_id, limit: int) -> int:
    """Снабженец — автор исходного документа поднимает лимит АП на него (D-S5-2):
    от числа уже поданных до 10, пока окно открыто."""
    source = source_of(source_type, source_id, lock=True)
    if source.author_id != actor.user_id or _author_role(actor) != InitiatorRole.SN.value \
            or not actor.can(NODE, "create"):
        raise _deny(f"Лимит альтернатив к документу {source.number} меняет его автор — "
                    f"снабженец.")
    if not window_open(source):
        raise _window_closed()
    filed = _decided_count(source)
    if not filed <= limit <= LIMIT_MAX or limit < 1:
        raise _bad("limit", f"Лимит — от {max(filed, 1)} (уже подано {filed}) до {LIMIT_MAX}.")
    before = source.alt_limit
    if before != limit:
        type(source).objects.filter(pk=source.pk).update(alt_limit=limit)
        source.alt_limit = limit
        audit.record(source, "alt_limit_changed", actor_id=actor.user_id,
                     changes={"before": before, "after": limit})
    return limit


# ── карточка ────────────────────────────────────────────────────────────

def serialize(actor: Actor, offer: AlternativeOffer) -> dict:
    source = _MODELS[offer.source_type].objects.filter(pk=offer.source_id).first()
    items = {row.pk: row for row in
             offer.lines.select_related("request_item").order_by("created_at")}
    brief = counterparties.brief([offer.counterparty_id] if offer.counterparty_id else [])

    def text(value):
        return None if value is None else str(value)

    return {
        "id": str(offer.pk), "number": offer.number, "version": offer.version,
        "status": offer.status, "status_label": offer.get_status_display(),
        "source": {
            "type": offer.source_type, "id": str(offer.source_id),
            "number": source.number if source else None,
            "currency_code": source.currency_code if source else None,
            "alt_limit": source.alt_limit if source else None,
            "window_open": bool(source and window_open(source)),
            "url": f"{_URLS[offer.source_type]}{offer.source_id}",
        },
        "project_id": text(offer.project_id), "article_id": text(offer.article_id),
        "author_id": offer.author_id, "author_role": offer.author_role,
        "own_document": offer.own_document,
        "counterparty_id": text(offer.counterparty_id),
        "counterparty": brief.get(str(offer.counterparty_id)),
        "currency_code": offer.currency_code, "rate": text(offer.rate),
        "amount": text(offer.amount), "amount_kzt": text(offer.amount_kzt),
        "with_vat": offer.with_vat, "vat_rate": text(offer.vat_rate),
        "vat_source": offer.vat_source, "vat_amount": text(offer.vat_amount),
        "source_amount_kzt": text(offer.source_amount_kzt),
        "saving_amount": text(offer.saving_amount), "saving_pct": text(offer.saving_pct),
        "delivery_date": offer.delivery_date, "payment_terms": offer.payment_terms,
        "payment_terms_note": offer.payment_terms_note, "justification": offer.justification,
        "submitted_at": offer.submitted_at, "decided_at": offer.decided_at,
        "decision_comment": offer.decision_comment, "closed_reason": offer.closed_reason,
        "lines": [{
            "id": str(line.pk), "source_line_id": str(line.source_line_id),
            "item": line.request_item.sys_number, "name": line.request_item.name,
            "qty": str(line.qty), "source_price": str(line.source_price),
            "price": text(line.price), "amount": text(line.amount),
        } for line in items.values()],
        "files": core_files.list_files(offer),
        "allowed_actions": allowed_actions(actor, offer),
    }
