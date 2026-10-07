"""Статус заявки tender — свёртка её частей (T1.3; план этапов 0–2, §3.3;
мастер-план T-08, T-09).

Каждая часть — ЗЗ в БЗО; её статус приходит слушателем
``bpp.register_request_listener`` в транзакции смены статуса ЗЗ (решение ТД,
ОД, отзыв, отмена). Слушатель пишет зеркало ``TenderRequestPart.bpp_status``
и пересчитывает статус заявки — только пока она в «Черновике», «На
согласовании», «Утверждена», «На доработке» или «Отклонена»: дальше (тендер,
передача, закрытие, отмена) статус ведёт сам tender. Исключение слушателя
откатывает и смену статуса ЗЗ.

Свёртка по неисключённым частям (приоритет ``rejected > rework > draft >
in_approval > approved``): есть «Отклонена» → «Отклонена»; иначе «На
доработке» (+ комментарий возврата последней); иначе «Черновик» (отзыв); иначе
«На согласовании»; иначе все «Утверждена» (часть может быть уже закрыта или
отменена) → «Утверждена»; все отменены/закрыты → «Отменена».
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from apps.tender.models import TenderRequest, TenderRequestPart, TenderRequestStatus
from apps.tender.services.core import audit

#: Статусы заявки, которые следуют за ЗЗ (§3.3).
ROLLED = (TenderRequestStatus.DRAFT, TenderRequestStatus.IN_APPROVAL,
          TenderRequestStatus.APPROVED, TenderRequestStatus.REWORK,
          TenderRequestStatus.REJECTED)
_ORDER = ("rejected", "rework", "draft", "in_approval")
_FINAL = {"cancelled", "closed"}

#: Заявки, по которым сейчас идёт действие пользователя в tender (отправка,
#: отзыв, отмена): статусы их ЗЗ меняет само действие, и слушатель только
#: обновляет зеркало частей — статус, версию и журнал заявки действие пишет
#: само, одной записью (одно действие — одна версия и одна строка журнала).
_ACTING: ContextVar[frozenset[str]] = ContextVar("tender_request_acting",
                                                  default=frozenset())


@contextmanager
def acting_on(request_id) -> Iterator[None]:
    token = _ACTING.set(_ACTING.get() | {str(request_id)})
    try:
        yield
    finally:
        _ACTING.reset(token)


def rolled_status(statuses) -> str:
    """Свёртка статусов ЗЗ неисключённых частей; пустой статус — часть ещё
    не отправлена (как «Черновик»). Частей не осталось — «Отменена»."""
    found = {status or "draft" for status in statuses}
    if not found or found <= _FINAL:
        return TenderRequestStatus.CANCELLED
    for status in _ORDER:
        if status in found:
            return status
    return TenderRequestStatus.APPROVED


def active_parts(req: TenderRequest):
    return req.parts.filter(excluded_at__isnull=True)


def excludable_parts(req: TenderRequest):
    """Части, которые «Исключить часть» примет: заявка в статусе свёртки
    (``ROLLED``), часть не исключена и её ЗЗ отклонена. Одно условие на
    кнопку карточки (``crud.allowed_actions``) и на сам переход
    (``submit.exclude_part``)."""
    if req.status not in ROLLED:
        return req.parts.none()
    return active_parts(req).filter(bpp_status="rejected")


def roll_up(req: TenderRequest, *, actor_id: int | None, rework_comment: str | None = None,
            reason: str = "") -> bool:
    """Пересчитать статус заявки ``req`` (строка уже заблокирована вызывающим);
    изменился — версия растёт, запись в журнал. ``True`` — статус сменился."""
    if req.status not in ROLLED:
        return False
    new = rolled_status(active_parts(req).values_list("bpp_status", flat=True))
    if new == req.status:
        if new == TenderRequestStatus.REWORK and rework_comment:
            req.rework_comment = rework_comment
            req.save(update_fields=["rework_comment", "updated_at"])
        return False
    before = req.status
    req.status = new
    if new == TenderRequestStatus.REWORK:
        req.rework_comment = rework_comment if rework_comment is not None else req.rework_comment
    req.version += 1
    if actor_id is not None:
        req.updated_by = actor_id
    req.save(update_fields=["status", "rework_comment", "version", "updated_by",
                            "updated_at"])
    audit.record(req, "status_rolled_up", actor_id=actor_id,
                 changes={"status": [before, new], "reason": reason})
    return True


def on_bpp_status(out) -> None:
    """Слушатель БЗО: ``out`` — ``bpp.interface.RequestStatusOut``. ЗЗ без
    части (её заводит отправка — часть узнает ключ после ответа БЗО) или
    чужая — пропуск."""
    part = (TenderRequestPart.objects.filter(bpp_request_id=out.bpp_request_id)
            .order_by("created_at").first())
    if part is None:
        return
    if str(part.request_id) in _ACTING.get():
        part.bpp_status, part.bpp_number = out.status, out.number
        part.save(update_fields=["bpp_status", "bpp_number", "updated_at"])
        return
    req = TenderRequest.objects.select_for_update().get(pk=part.request_id)
    if part.bpp_status != out.status or part.bpp_number != out.number:
        before = part.bpp_status
        part.bpp_status, part.bpp_number = out.status, out.number
        part.save(update_fields=["bpp_status", "bpp_number", "updated_at"])
        audit.record(req, "part_status", actor_id=None,
                     changes={"part": str(part.pk), "bpp_number": out.number,
                              "bpp_status": [before, out.status]})
    roll_up(req, actor_id=None,
            rework_comment=out.rework_comment if out.status == "rework" else None,
            reason=f"{out.number}: {out.status}")
