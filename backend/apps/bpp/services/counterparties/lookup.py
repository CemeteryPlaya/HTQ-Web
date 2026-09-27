"""Контрагент глазами документов — функции для договора и счёта (B, этап 3).

- ``brief(ids)`` — короткие карточки для реестров и форм;
- ``assert_usable(id)`` — можно ли поставить контрагента в новый документ:
  заблокированный — E-CTR-01 дословно ТЗ §26.1, архивный — свой текст;
- ``needs_confirmation(id)`` — нужно ли окно подтверждения автора при
  отправке документа (D-20: у непроверенного — да, у проверенного — нет);
- ``record_success(id)`` — засчитать удачный документ: договор
  «Действует»/«Исполнен» или счёт «Оплачено». Зовёт B в той транзакции,
  где документ перешёл в этот статус.

«Проверенный» = ``verified_override``, если ФД решил вручную, иначе
``successful_documents`` ≥ порога ``counterparty_verified_threshold``.
"""

from __future__ import annotations

import uuid
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db.models import F

from apps.bpp.models.counterparties import Counterparty, CounterpartyStatus
from apps.bpp.services.core import audit
from apps.bpp.services.core.settings import get_setting
from htqweb.errors import DomainError

__all__ = [
    "as_uuid",
    "assert_usable",
    "brief",
    "display_name",
    "get",
    "is_verified",
    "needs_confirmation",
    "record_success",
    "verified_threshold",
]

THRESHOLD_KEY = "counterparty_verified_threshold"


def verified_threshold() -> int:
    return int(get_setting(THRESHOLD_KEY))


def is_verified(cp: Counterparty, threshold: int | None = None) -> bool:
    if cp.verified_override is not None:
        return bool(cp.verified_override)
    threshold = verified_threshold() if threshold is None else threshold
    return cp.successful_documents >= threshold


def display_name(cp: Counterparty) -> str:
    return cp.short_name or cp.name


def as_uuid(value) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None


def _not_found() -> DomainError:
    return DomainError("E-NOT-FOUND", "Контрагент не найден.", status=404,
                       fields=[{"field": "counterparty_id", "message": "Контрагент не найден"}])


def get(counterparty_id) -> Counterparty:
    key = as_uuid(counterparty_id)
    cp = Counterparty.objects.filter(pk=key).first() if key else None
    if cp is None:
        raise _not_found()
    return cp


def brief(ids) -> dict[str, dict]:
    keys = [key for key in (as_uuid(i) for i in set(ids or ())) if key]
    if not keys:
        return {}
    threshold = verified_threshold()
    return {str(cp.pk): {
        "id": str(cp.pk), "name": cp.name, "short_name": cp.short_name,
        "reg_number": cp.reg_number, "country_code": cp.country_code,
        "is_vat_payer": cp.is_vat_payer, "status": cp.status,
        "is_verified": is_verified(cp, threshold),
    } for cp in Counterparty.objects.filter(pk__in=keys)}


def assert_usable(counterparty_id) -> Counterparty:
    """Контрагент годится для нового документа; иначе — отказ с текстом для
    автора. Возвращает сам контрагент, чтобы не читать его второй раз."""
    cp = get(counterparty_id)
    if cp.status == CounterpartyStatus.BLOCKED:
        when = "—"
        if cp.blocked_at:
            # Дату читает человек — в поясе платформы, а не хранения (UTC).
            zone = ZoneInfo(settings.PLATFORM_TIME_ZONE)
            when = cp.blocked_at.astimezone(zone).strftime("%d.%m.%Y")
        raise DomainError(
            "E-CTR-01",
            f"Контрагент {display_name(cp)} заблокирован {when}: „{cp.block_reason}“. "
            f"Выберите другого контрагента или обратитесь к финансовому директору.",
            fields=[{"field": "counterparty_id", "message": "Контрагент заблокирован"}])
    if cp.status == CounterpartyStatus.ARCHIVED:
        raise DomainError(
            "E-CTR-01",
            f"Контрагент {display_name(cp)} переведён в архив и в новых документах не "
            f"используется. Выберите другого контрагента или обратитесь к финансовому "
            f"директору.",
            fields=[{"field": "counterparty_id", "message": "Контрагент в архиве"}])
    return cp


def needs_confirmation(counterparty_id) -> bool:
    return not is_verified(get(counterparty_id))


def record_success(counterparty_id) -> None:
    """+1 удачный документ — атомарно в БД (``F() + 1``), без чтения строки:
    два документа, ставшие удачными одновременно, засчитываются оба.
    Версию карточки не трогает — это не правка пользователя, и форма,
    открытая у ФД, не должна получить E-CON-01 из-за оплаты счёта."""
    key = as_uuid(counterparty_id)
    if key is None or not Counterparty.objects.filter(pk=key).update(
            successful_documents=F("successful_documents") + 1):
        raise _not_found()
    # В журнал — каждый удачный документ: метка «Проверенный» появляется
    # сама, и «История изменений» обязана показать, когда (ТЗ §25.2).
    cp = Counterparty.objects.get(pk=key)
    audit.record_for("bpp.counterparty", str(key), "success_recorded", actor_id=None,
                     changes={"successful_documents": cp.successful_documents,
                              "verified": is_verified(cp)})
