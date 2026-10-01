"""Жизненный цикл альтернативных предложений и контракт выбора для B5.1
(ТЗ §12.2, §12.4 п.3, 6, 7, §12.5, BR-096; план этапа 5 A, задача 3, D-S5-6).

**Закрытие АП по решению об исходном документе** — ``close_for_source``. Её
зовут хуки счёта и договора (зона B, одной строкой в транзакции смены
статуса), до ``kpi.sync_for_document``:

- «Оплатить» по счёту, утверждение договора в исходном варианте —
  ``"not_selected"``: «Подано» → «Не выбрано» (§12.4 п.6), черновик →
  «Аннулировано» (подать его уже нельзя);
- «Не к оплате», возврат на доработку, отмена счёта; отклонение, доработка,
  отзыв договора — ``"annulled"``: и поданные, и черновики → «Аннулировано»
  (§12.4 п.7). При повторной отправке документа окно открывается снова, и
  СН подаёт АП заново — новой строкой.

**Выбор** делает B (B5.1) поверх ``mark_selected``/``options_for``/
``check_option``: этот модуль только переводит АП, ни исходный документ, ни
новый он не пишет. Порядок в транзакции выбора — ``mark_selected`` до смены
статуса исходного документа и до ``close_for_source`` (иначе выбранная уже
закрыта), затем черновик нового документа и ``kpi.create_preliminary``.

**Уведомление снабженцам** — ``notify_buyers`` из ``on_started`` счёта без
договора и договора (§12.2): каждая отправка, в том числе повторная.

**Порядок блокировок** — как у подачи (``offers._locked``): строка
исходного документа, затем строки АП. Решение ФД (``invoices.lock``),
колбэки signoff (``UPDATE`` строки документа) и подача АП поэтому
сериализуются (Review Focus 2): кто второй, тот видит результат первого, и
«Подано» к решённому документу не остаётся.

Модуль зовётся из сервисов счёта и договора, поэтому их не импортирует
(цикл): модели читает напрямую, как весь подмодуль.
"""

from __future__ import annotations

import uuid

from django.db import transaction
from django.utils import timezone

from apps.access import interface as access
from apps.bpp.models import AlternativeOffer, Invoice, InvoiceBasis, OfferStatus
from apps.bpp.models.alternatives import OfferSource
from apps.bpp.services.alternatives import offers
from apps.bpp.services.core import audit
from apps.bpp.services.counterparties import lookup as counterparties
from apps.bpp.services.money import fmt
from apps.core.services import ServiceDisabled, service_enabled
from apps.notifications import interface as notifications
from apps.users import interface as users
from htqweb.errors import DomainError
from htqweb.fallback import fallback
from htqweb.tenancy import current_company_or_none

__all__ = [
    "ANNULLED", "NOT_SELECTED", "ORIGINAL", "SOURCE_AGREEMENT", "SOURCE_INVOICE",
    "check_option", "close_for_source", "mark_selected", "notify_buyers", "offers_for",
    "options_for",
]

SOURCE_INVOICE = OfferSource.INVOICE.value
SOURCE_AGREEMENT = OfferSource.AGREEMENT.value

#: Исходы ``close_for_source``.
NOT_SELECTED = "not_selected"
ANNULLED = "annulled"

#: Ключ варианта «исходный документ» для голосов signoff; альтернатива — ``offer:<uuid>``.
ORIGINAL = "original"
OFFER_PREFIX = "offer:"

#: Причины закрытия — текст ``closed_reason`` и уведомления автору АП.
REASON_INVOICE_PAY = "Счёт принят к оплате без выбора альтернативы"
REASON_INVOICE_NOT_PAYABLE = "Счёт отклонён — «Не к оплате»"
REASON_INVOICE_CANCELLED = "Счёт отменён"
REASON_AGREEMENT_APPROVED = "Договор утверждён в исходном варианте"
REASON_AGREEMENT_REJECTED = "Договор отклонён"
REASON_AGREEMENT_WITHDRAWN = "Договор отозван автором"
REASON_RETURNED = "Документ возвращён на доработку"

OPTION_GONE = "Альтернатива отозвана или уже не действует"
EVENT_CLOSED = "bpp.alternative_closed"
EVENT_SELECTED = "bpp.alternative_selected"
EVENT_WINDOW = "bpp.alternative_window"

_KIND_LABEL = {SOURCE_INVOICE: "счёт", SOURCE_AGREEMENT: "договор"}
_ROLE_LABEL = {"sn": "СН", "pm": "ПМ"}
_OUTCOME_STATUS = {
    NOT_SELECTED: {OfferStatus.SUBMITTED: OfferStatus.NOT_SELECTED,
                   OfferStatus.DRAFT: OfferStatus.ANNULLED},
    ANNULLED: {OfferStatus.SUBMITTED: OfferStatus.ANNULLED,
               OfferStatus.DRAFT: OfferStatus.ANNULLED},
}


def _key(value) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None


def _state(text: str) -> DomainError:
    return DomainError("E-STATE-01", text, status=409)


# ── чтение ──────────────────────────────────────────────────────────────

def offers_for(source_type: str, source_id, *, statuses=(OfferStatus.SUBMITTED.value,)
               ) -> list[AlternativeOffer]:
    """АП документа в ``statuses`` по номеру (порядок подачи)."""
    key = _key(source_id)
    if key is None:
        return []
    return list(AlternativeOffer.objects.select_related("counterparty")
                .filter(source_type=source_type, source_id=key, status__in=list(statuses))
                .order_by("number"))


def _offer_label(offer: AlternativeOffer) -> str:
    party = counterparties.display_name(offer.counterparty) if offer.counterparty else "—"
    return f"Альтернатива {offer.number} — {party}, {fmt(offer.amount, offer.currency_code)}"


def options_for(source_type: str, source_id) -> list[dict]:
    """Варианты голоса signoff (ТЗ §12.4 п.1): исходный документ и все
    поданные АП по номеру. Документа нет — пустой список."""
    source = offers._MODELS.get(source_type)
    key = _key(source_id)
    row = source.objects.filter(pk=key).first() if source is not None and key else None
    if row is None:
        return []
    return [{"key": ORIGINAL, "label": f"Исходный документ {row.number}"},
            *({"key": f"{OFFER_PREFIX}{offer.pk}", "label": _offer_label(offer)}
              for offer in offers_for(source_type, key))]


def check_option(source_type: str, source_id, option_key: str) -> str | None:
    """Можно ли голосовать за вариант: ``None`` — да, иначе причина."""
    if option_key == ORIGINAL:
        return None
    if not isinstance(option_key, str) or not option_key.startswith(OFFER_PREFIX):
        return "Неизвестный вариант голоса"
    offer_key, key = _key(option_key[len(OFFER_PREFIX):]), _key(source_id)
    if offer_key is None or key is None:
        return OPTION_GONE
    alive = AlternativeOffer.objects.filter(
        pk=offer_key, source_type=source_type, source_id=key,
        status=OfferStatus.SUBMITTED).exists()
    return None if alive else OPTION_GONE


# ── переходы ────────────────────────────────────────────────────────────

def _lock_source(source_type: str, source_id):
    """Строка исходного документа под замком — первый замок, как у подачи.
    Документа нет (удалён) — ``None``: АП закрываются и без него."""
    model = offers._MODELS.get(source_type)
    key = _key(source_id)
    if model is None or key is None:
        return None
    return model.objects.select_for_update().filter(pk=key).first()


def _locked_offers(source_type: str, source_id, statuses) -> list[AlternativeOffer]:
    return list(AlternativeOffer.objects.select_for_update()
                .filter(source_type=source_type, source_id=source_id,
                        status__in=[str(s) for s in statuses])
                .order_by("number"))


def _move(offer: AlternativeOffer, status: str, *, actor_id: int | None, action: str,
          reason: str = "", comment: str = "", **fields) -> None:
    before = offer.status
    offer.status = status
    if reason:
        offer.closed_reason = reason
    for name, value in fields.items():
        setattr(offer, name, value)
    offer.version += 1
    offer.updated_by = actor_id
    offer.save()
    audit.record(offer, action, actor_id=actor_id, comment=comment or reason,
                 changes={"status": [before, status]})


def _notify(recipient_id: int, *, event: str, title: str, offer: AlternativeOffer,
            actor_id: int | None) -> None:
    """Уведомление автору АП. Запись — под своей точкой сохранения: сбой
    центра смену статуса не роняет, но и не глотается молча."""
    company = current_company_or_none()
    if company is None:
        fallback("bpp.alternatives.lifecycle_notify_no_company", None, expected=True,
                 reason="нет контекста компании — автор альтернативы не уведомлён",
                 offer=str(offer.pk))
        return
    if recipient_id == actor_id:
        return
    try:
        with transaction.atomic():
            notifications.notify(
                recipients=[recipient_id], event=event, title=title,
                url=f"/bpp/alternatives/{offer.pk}", company_slug=company,
                target_type=offer._meta.label_lower, target_id=str(offer.pk),
                actor_id=actor_id, deliver=True)
    except ServiceDisabled as exc:
        fallback("bpp.alternatives.lifecycle_notify_disabled", None, expected=True, exc=exc,
                 reason="центр уведомлений выключен — автор альтернативы не уведомлён",
                 offer=str(offer.pk))
    except Exception as exc:
        fallback("bpp.alternatives.lifecycle_notify_failed", None, exc=exc,
                 reason="центр уведомлений не принял уведомление о закрытии альтернативы",
                 offer=str(offer.pk))


def _close(rows: list[AlternativeOffer], outcome: str, *, reason: str, source_number: str,
           actor_id: int | None = None) -> int:
    moves = _OUTCOME_STATUS[outcome]
    closed = 0
    for offer in rows:
        target = moves.get(offer.status)
        if target is None:
            continue
        _move(offer, target, actor_id=actor_id, action=OfferStatus(target).value,
              reason=reason)
        label = OfferStatus(target).label
        _notify(offer.author_id, event=EVENT_CLOSED, offer=offer, actor_id=actor_id,
                title=f"Альтернатива {offer.number} к {source_number}: «{label}». {reason}")
        closed += 1
    return closed


@transaction.atomic
def close_for_source(source_type: str, source_id, outcome: str, *, reason: str) -> int:
    """Закрыть действующие АП документа по решению о нём (D-S5-6).

    ``outcome="not_selected"`` — «Подано» → «Не выбрано», черновик →
    «Аннулировано»; ``"annulled"`` — обе → «Аннулировано». ``reason`` —
    ``closed_reason`` и текст уведомления автору. Возвращает число закрытых
    АП; повторный вызов ничего не меняет (закрывать уже нечего)."""
    if outcome not in _OUTCOME_STATUS:
        raise ValueError(f"Неизвестный исход закрытия альтернатив: {outcome!r}")
    key = _key(source_id)
    if source_type not in offers._MODELS or key is None:
        return 0
    source = _lock_source(source_type, key)
    rows = _locked_offers(source_type, key, (OfferStatus.DRAFT, OfferStatus.SUBMITTED))
    if not rows:
        return 0
    number = source.number if source is not None else str(key)
    return _close(rows, outcome, reason=reason, source_number=number)


@transaction.atomic
def mark_selected(offer_id, *, actor_id: int, comment: str) -> AlternativeOffer:
    """Выбор АП (ТЗ §12.4 п.3; зовёт B5.1 в транзакции выбора, до смены
    статуса исходного документа): выбранная → «Выбрано» (``decided_by``,
    ``decided_at``, ``decision_comment``), прочие «Подано» → «Не выбрано»,
    черновики → «Аннулировано».

    Документ уже заменён (есть «Выбрано», в том числе эта же АП) — 409
    ``E-STATE-01`` (BR-096); АП не «Подано» или окно документа закрыто —
    409 ``E-STATE-01``; АП нет (в том числе удалена между пробой и замком) —
    404 ``E-NOT-FOUND``."""
    key = _key(offer_id)
    probe = AlternativeOffer.objects.filter(pk=key).first() if key else None
    if probe is None:
        raise DomainError("E-NOT-FOUND", "Альтернатива не найдена.", status=404)
    source = offers.source_of(probe.source_type, probe.source_id, lock=True)
    rows = _locked_offers(probe.source_type, probe.source_id, OfferStatus.values)
    offer = next((row for row in rows if row.pk == probe.pk), None)
    if offer is None:  # удалена между пробой и замком
        raise DomainError("E-NOT-FOUND", "Альтернатива не найдена.", status=404)
    if any(row.status == OfferStatus.SELECTED for row in rows):
        raise _state("Документ уже заменён альтернативой")
    if offer.status != OfferStatus.SUBMITTED:
        raise _state(OPTION_GONE)
    if not offers.window_open(source):
        raise _state("Документ уже решён — альтернатива не выбирается")
    comment = (comment or "").strip()
    _move(offer, OfferStatus.SELECTED, actor_id=actor_id, action="selected", comment=comment,
          decided_by_id=actor_id, decided_at=timezone.now(), decision_comment=comment)
    _notify(offer.author_id, event=EVENT_SELECTED, offer=offer, actor_id=actor_id,
            title=f"Альтернатива {offer.number} к {source.number} выбрана")
    _close([row for row in rows if row.pk != offer.pk], NOT_SELECTED,
           reason=f"Выбрана альтернатива {offer.number}", source_number=source.number,
           actor_id=actor_id)
    return offer


# ── уведомление снабженцам ──────────────────────────────────────────────

def _short_name(user_id: int) -> str:
    """«Иванов А.» (ТЗ §12.2): полное имя платформы — «Имя Фамилия»."""
    brief = users.get_user_brief(user_id) or {}
    parts = (brief.get("full_name") or "").split()
    if len(parts) == 2:
        return f"{parts[1]} {parts[0][0]}."
    return " ".join(parts) or f"#{user_id}"


def _offerable(source) -> bool:
    """К этому документу АП вообще подаются (``offers._check_kind``)."""
    if isinstance(source, Invoice):
        return source.basis == InvoiceBasis.NO_CONTRACT
    return not source.is_open and source.parent_agreement_id is None


def notify_buyers(source_type: str, source_id) -> None:
    """Всем снабженцам — держателям ``bpp.alternatives`` create, кроме автора
    документа: документ отправлен, можно предложить альтернативу (ТЗ §12.2).
    Счёт по договору, открытый договор и допсоглашение не объявляются —
    к ним АП не подаётся; выключенный у компании подмодуль — тоже."""
    model = offers._MODELS.get(source_type)
    key = _key(source_id)
    source = model.objects.filter(pk=key).first() if model is not None and key else None
    if source is None or not _offerable(source):
        return
    if not service_enabled("bpp_alternatives"):
        return
    company = current_company_or_none()
    if company is None:
        fallback("bpp.alternatives.buyers_notify_no_company", None, expected=True,
                 reason="нет контекста компании — снабженцы не уведомлены",
                 source=str(source.pk))
        return
    try:
        recipients = set(access.holders_of(offers.NODE, "create", company))
        recipients.discard(source.author_id)
        if not recipients:
            return
        role = _ROLE_LABEL.get(source.initiator_role, "")
        who = f"{role} {_short_name(source.author_id)}".strip()
        party = counterparties.display_name(source.counterparty) if source.counterparty else ""
        amount = fmt(source.amount, source.currency_code) if source.amount is not None else ""
        what = f"{_KIND_LABEL[source_type]} {source.number}"
        if amount:
            what += f" на {amount}"
        if party:
            what += f", {party}"
        with transaction.atomic():
            notifications.notify(
                recipients=sorted(recipients), event=EVENT_WINDOW,
                title=f"{who} отправил {what}. Можно предложить альтернативу",
                url=f"/bpp/alternatives?source={source_type}:{source.pk}",
                company_slug=company, target_type=source._meta.label_lower,
                target_id=str(source.pk), actor_id=source.author_id, deliver=True)
    except ServiceDisabled as exc:
        fallback("bpp.alternatives.buyers_notify_disabled", None, expected=True, exc=exc,
                 reason="центр уведомлений выключен — снабженцы не уведомлены",
                 source=str(source.pk))
    except Exception as exc:
        fallback("bpp.alternatives.buyers_notify_failed", None, exc=exc,
                 reason="центр уведомлений не принял уведомление снабженцам",
                 source=str(source.pk))
