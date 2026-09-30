"""KPI снабжения: запись, подтверждение по новому документу, аннулирование
(ТЗ §12.5, BR-095, BR-096; план этапа 5 A, задача 5 — A5.2).

Запись KPI заводит выбор альтернативы (B5.1) — ``create_preliminary`` в
транзакции выбора. Дальше её судьбу ведёт статус НОВОГО документа
(D-S5-7): его хуки (зона B) зовут ``sync_for_document`` на каждой смене
статуса счёта или договора.

- ``sync_for_document`` идемпотентна (D-S5-8): читает текущий статус
  документа, а не «что случилось»; лишний вызов ничего не меняет,
  пропущенный лечится следующим. Запись берётся ``select_for_update``.
- «Подтверждён» не откатывается в «Предварительный» (снятая отметка БУХ,
  допсоглашение к новому договору); «Аннулирован» финален. Сумма нового
  документа и экономия пересчитываются только у «Предварительного»
  (CALC-013) и замораживаются в момент подтверждения.
- Подтверждённую запись система аннулирует по тому же правилу, что и
  предварительную (ТЗ §12.5): новый счёт «Не к оплате»/«Отменён»/«Заменён»,
  новый договор «Отклонён» или «Расторгнут» без оплаченных счетов.
- ``annul`` — ручное аннулирование ФД с комментарием (узел ``bpp.kpi`` edit).

Модуль зовётся из зоны B, поэтому не импортирует сервисы счёта и договора
на уровне модуля (циклы): модели читает напрямую, как весь подмодуль.
"""

from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.bpp.models import (
    AgreementStatus,
    AlternativeOffer,
    InvoiceStatus,
    KpiRecord,
    KpiStatus,
    OfferSource,
    OfferStatus,
)
from apps.bpp.models.agreements import Agreement
from apps.bpp.models.invoices import Invoice
from apps.bpp.services import calc as money_calc
from apps.bpp.services.actor import Actor
from apps.bpp.services.alternatives import calc
from apps.bpp.services.core import audit
from apps.bpp.services.core.errors import DomainError, check_version
from apps.bpp.services.money import money

__all__ = ["COMMENT_MIN", "NODE", "annul", "can_view", "create_preliminary", "get_visible",
           "sees_all", "sync_for_document"]

NODE = "bpp.kpi"
COMMENT_MIN = 10

#: Счёт подтверждает оплата и всё после неё по оси закрывающих (D-13).
INVOICE_CONFIRMS = (InvoiceStatus.PAID, InvoiceStatus.AWAITING_DOCS,
                    InvoiceStatus.DOCS_PROVIDED, InvoiceStatus.CLOSED)
INVOICE_ANNULS = (InvoiceStatus.NOT_PAYABLE, InvoiceStatus.CANCELLED, InvoiceStatus.REPLACED)
#: Статусы счёта, где есть отметка оплаты БУХ (для «Расторгнут без оплаченных»).
PAID_GROUP = (InvoiceStatus.PARTIALLY_PAID, *INVOICE_CONFIRMS)
AGREEMENT_CONFIRMS = (AgreementStatus.ACTIVE, AgreementStatus.FULFILLED)


def _deny(text: str) -> DomainError:
    return DomainError("E-ACC-01", f"У вас нет прав: {text}. Если это ошибка, обратитесь к "
                                   f"администратору.", status=403)


# ── видимость ───────────────────────────────────────────────────────────

def sees_all(actor: Actor) -> bool:
    """Все записи видят ФД, ОД, ГД; СН — только свои (D-S5-9, ТЗ §12.6).
    Отличие то же, что у АП и реестра счетов: право оформлять счета есть
    у СН и ПМ, у руководителей его нет."""
    if getattr(actor.request.token, "is_superuser", False):
        return True
    return not actor.can("bpp.invoices", "create")


def can_view(actor: Actor, kpi: KpiRecord) -> bool:
    """Запись видна тому, у кого ``bpp.kpi`` view; СН — только свою.
    Проверка журнала записи (``HISTORY_CHECKS``) — та же."""
    if not actor.can(NODE, "view"):
        return False
    return sees_all(actor) or kpi.buyer_id == actor.user_id


def get_visible(actor: Actor, kpi_id) -> KpiRecord:
    """Карточка записи; чужая и несуществующая — 404 (не подтверждаем
    существование чужой строки)."""
    if not actor.can(NODE, "view"):
        raise _deny("просмотр KPI снабжения")
    kpi = KpiRecord.objects.filter(pk=kpi_id).first()
    if kpi is None or not can_view(actor, kpi):
        raise DomainError("E-NOT-FOUND", "Запись KPI не найдена.", status=404)
    return kpi


# ── документы ───────────────────────────────────────────────────────────

def _document(doc_type: str, doc_id, *, lock: bool = False):
    model = {OfferSource.INVOICE: Invoice, OfferSource.AGREEMENT: Agreement}.get(doc_type)
    if model is None:
        return None
    query = model.objects.select_for_update() if lock else model.objects
    return query.filter(pk=doc_id).first()


def _agreement_kzt(agr: Agreement, previous: Decimal | None) -> Decimal | None:
    """Сумма договора в KZT. Открытый договор суммы не имеет. Курса нет —
    остаётся прежнее значение (пересчёт «на курс» не должен стирать цифру).
    Допсоглашения не входят: у договора учитывается его собственная сумма
    (подтверждённая экономия допсоглашением не меняется, D-S5-7)."""
    if agr.is_open or agr.amount is None:
        return None
    if agr.currency_code == "KZT":
        return money(agr.amount)
    try:
        return money_calc.to_kzt(agr.amount, agr.currency_code,
                                 agr.ext_date or timezone.localdate()).amount_kzt
    except DomainError:
        return previous


def _result_amount(doc, previous: Decimal | None) -> Decimal | None:
    if isinstance(doc, Invoice):
        return doc.amount_kzt if doc.amount_kzt is not None else previous
    return _agreement_kzt(doc, previous)


def _saving(kpi: KpiRecord) -> tuple[Decimal | None, Decimal | None]:
    if kpi.result_amount_kzt is None:
        return None, None
    return calc.saving(kpi.source_amount_kzt, kpi.result_amount_kzt)


def _touch(kpi: KpiRecord, actor_id: int | None, *fields: str) -> None:
    kpi.version += 1
    kpi.updated_by = actor_id
    kpi.save(update_fields=["version", "updated_by", "updated_at", *fields])


# ── запись ──────────────────────────────────────────────────────────────

@transaction.atomic
def create_preliminary(offer_id, *, result_type: str, result_id, selected_by_id: int
                       ) -> KpiRecord:
    """Запись «Предварительный» по выбранной АП (BR-096: одна на АП).

    Снимок: покупатель и его роль, «К своему документу», проект и статья,
    исходный документ и его номер, контрагент исходного, исходная часть в
    KZT (``offer.source_amount_kzt``), новый документ и его текущая сумма,
    экономия CALC-013. Зовёт выбор (B5.1) в своей транзакции, после
    ``lifecycle.mark_selected`` и создания черновика нового документа."""
    offer = AlternativeOffer.objects.select_for_update().filter(pk=offer_id).first()
    if offer is None:
        raise DomainError("E-NOT-FOUND", "Альтернативное предложение не найдено.", status=404)
    if offer.status != OfferStatus.SELECTED:
        raise DomainError("E-STATE-01", f"Запись KPI заводится по выбранной альтернативе; "
                                        f"{offer.number} — «{offer.get_status_display()}».",
                          status=409)
    if KpiRecord.objects.filter(offer=offer).exists():
        raise DomainError("E-STATE-01", f"По альтернативе {offer.number} запись KPI уже есть.",
                          status=409)
    result = _document(result_type, result_id)
    if result is None:
        raise DomainError("E-NOT-FOUND", "Новый документ по альтернативе не найден.",
                          status=404)
    source = _document(offer.source_type, offer.source_id)
    if source is None:
        raise DomainError("E-NOT-FOUND", "Исходный документ альтернативы не найден.",
                          status=404)
    if offer.source_amount_kzt is None:
        raise DomainError("E-VAL-01", "У альтернативы не рассчитана исходная часть.",
                          fields=[{"field": "source_amount_kzt", "message": "Пусто"}])
    kpi = KpiRecord(
        offer=offer, buyer_id=offer.author_id, buyer_role=offer.author_role,
        own_document=offer.own_document,
        project_id=offer.project_id or source.project_id,
        article_id=offer.article_id or source.article_id,
        source_type=offer.source_type, source_id=offer.source_id, source_number=source.number,
        source_counterparty_id=source.counterparty_id,
        source_amount_kzt=offer.source_amount_kzt,
        result_type=result_type, result_id=result.pk, result_number=result.number,
        result_amount_kzt=_result_amount(result, None),
        selected_at=timezone.now(), selected_by_id=selected_by_id,
        status=KpiStatus.PRELIMINARY, created_by=selected_by_id, updated_by=selected_by_id)
    kpi.saving_amount, kpi.saving_pct = _saving(kpi)
    kpi.save()
    audit.record(kpi, "created", actor_id=selected_by_id, changes={
        "offer": offer.number, "source": kpi.source_number, "result": kpi.result_number,
        "source_amount_kzt": str(kpi.source_amount_kzt),
        "result_amount_kzt": str(kpi.result_amount_kzt)
        if kpi.result_amount_kzt is not None else None,
        "saving_amount": str(kpi.saving_amount) if kpi.saving_amount is not None else None})
    return kpi


def _target_status(kpi: KpiRecord, doc) -> str | None:
    """Статус, в который документ переводит KPI (D-S5-7); ``None`` — без
    смены статуса (для «Предварительного» — пересчёт сумм)."""
    if isinstance(doc, Invoice):
        if doc.status in INVOICE_CONFIRMS:
            return KpiStatus.CONFIRMED
        if doc.status in INVOICE_ANNULS:
            return KpiStatus.ANNULLED
        return None
    if doc.status in AGREEMENT_CONFIRMS:
        return KpiStatus.CONFIRMED
    if doc.status == AgreementStatus.REJECTED:
        return KpiStatus.ANNULLED
    if doc.status == AgreementStatus.TERMINATED and not Invoice.objects.filter(
            agreement=doc, status__in=PAID_GROUP).exists():
        return KpiStatus.ANNULLED
    return None


def _annul_reason(doc) -> str:
    return f"{doc.number}: {doc.get_status_display()}"


@transaction.atomic
def sync_for_document(doc_type: str, doc_id) -> None:
    """Привести запись KPI в соответствие статусу нового документа (D-S5-8).

    Нет записи по документу — ничего (обычный счёт или договор). Вызов
    идемпотентен и безопасен на любом статусе."""
    kpi = (KpiRecord.objects.select_for_update()
           .filter(result_type=doc_type, result_id=doc_id).first())
    if kpi is None or kpi.status == KpiStatus.ANNULLED:
        return
    doc = _document(doc_type, doc_id)
    if doc is None:
        return
    target = _target_status(kpi, doc)
    now = timezone.now()
    if target == KpiStatus.ANNULLED:
        before = kpi.status
        kpi.status, kpi.status_changed_at = KpiStatus.ANNULLED, now
        kpi.annul_comment = f"Новый документ аннулирован системой ({_annul_reason(doc)})"
        _touch(kpi, None, "status", "status_changed_at", "annul_comment")
        audit.record(kpi, "annulled_system", actor_id=None, comment=kpi.annul_comment,
                     changes={"status": [before, KpiStatus.ANNULLED]})
        return
    if kpi.status == KpiStatus.CONFIRMED:
        return  # заморожен: не откатывается, сумма и экономия прежние
    # «Предварительный»: новая сумма → экономия (CALC-013); подтверждение
    # замораживает то, что посчитано в этот момент.
    fields = []
    changes: dict = {}
    number = doc.number
    if number != kpi.result_number:
        changes["result_number"] = [kpi.result_number, number]
        kpi.result_number = number
        fields.append("result_number")
    amount = _result_amount(doc, kpi.result_amount_kzt)
    if amount != kpi.result_amount_kzt:
        changes["result_amount_kzt"] = [_s(kpi.result_amount_kzt), _s(amount)]
        kpi.result_amount_kzt = amount
        fields.append("result_amount_kzt")
        saving_amount, saving_pct = _saving(kpi)
        changes["saving_amount"] = [_s(kpi.saving_amount), _s(saving_amount)]
        kpi.saving_amount, kpi.saving_pct = saving_amount, saving_pct
        fields += ["saving_amount", "saving_pct"]
    if target == KpiStatus.CONFIRMED:
        changes["status"] = [kpi.status, KpiStatus.CONFIRMED]
        kpi.status, kpi.status_changed_at = KpiStatus.CONFIRMED, now
        fields += ["status", "status_changed_at"]
    if not fields:
        return
    _touch(kpi, None, *fields)
    audit.record(kpi, "confirmed" if target == KpiStatus.CONFIRMED else "recalculated",
                 actor_id=None, changes=changes)


def _s(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


@transaction.atomic
def annul(actor: Actor, kpi_id, *, comment: str, expected_version: int | None) -> KpiRecord:
    """Ручное аннулирование записи ФД (ТЗ §12.5): «Предварительный» или
    «Подтверждён», комментарий не короче 10 знаков (BR-060)."""
    if not actor.can(NODE, "edit"):
        raise _deny("аннулирование KPI снабжения — действие финансового директора")
    kpi = KpiRecord.objects.select_for_update().filter(pk=kpi_id).first()
    if kpi is None:
        raise DomainError("E-NOT-FOUND", "Запись KPI не найдена.", status=404)
    comment = (comment or "").strip()
    if len(comment) < COMMENT_MIN:
        raise DomainError(
            "BR-060", "Опишите причину: комментарий не короче 10 символов.",
            fields=[{"field": "comment", "message": f"Минимум {COMMENT_MIN} символов"}])
    if kpi.status == KpiStatus.ANNULLED:
        raise DomainError("E-STATE-01", "Запись KPI уже аннулирована.", status=409)
    check_version(kpi, expected_version)
    before = kpi.status
    kpi.status, kpi.status_changed_at = KpiStatus.ANNULLED, timezone.now()
    kpi.annul_comment, kpi.annulled_by_id = comment, actor.user_id
    _touch(kpi, actor.user_id, "status", "status_changed_at", "annul_comment",
           "annulled_by_id")
    audit.record(kpi, "annulled", actor_id=actor.user_id, comment=comment,
                 changes={"status": [before, KpiStatus.ANNULLED]})
    return kpi
