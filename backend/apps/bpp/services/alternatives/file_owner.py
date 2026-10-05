"""КП альтернативного предложения — владелец ``bpp.alternative_offer`` в
``apps.files`` (ТЗ §12.3, §21; план этапа 5 A, задача 1). Подключается сам:
``apps/bpp/file_owners.py`` находит ``services/<подмодуль>/file_owner.py``
и зовёт ``register()`` (D-S3-1).

- Тип ``alternative_offer`` («КП»: PDF, DOCX, JPG, PNG до 10 МБ — ТЗ §12.3;
  справочник, миграция ``files/0005_bpp_alternative_offer_type``), до пяти
  документов на АП; обязателен для подачи (проверяет ``offers.submit``).
- Видит КП тот, кто видит АП: ``read.can_view`` (задача 4) — одна
  проверка на карточку, журнал и файлы (ПМ — только АП к своим документам).
- Менять КП через панель может только автор и только в «Черновике»:
  поданная АП — предмет сравнения и решения, её КП не подменяется.
- «Отправлялась» — статус не «Черновик»: удалённый черновик стирает свои
  файлы физически, у поданной АП они остаются.

Здесь же — доступ к «Истории изменений» АП и записей KPI (``audit.
register_history_access``). Модели сервисов не импортируют, а этот
``register()`` — единственный стартовый крючок подмодуля (зовётся из
``BppConfig.ready()``). Проверки берутся по пути импорта строкой и
разрешаются при первом чтении журнала: их модули (``read.py`` — задача 4,
``kpi.py`` — задача 5) импортируют сервисы счёта и договора, и тянуть их на
запуске ради регистрации незачем.
"""

from __future__ import annotations

import uuid

from django.utils.module_loading import import_string

from apps.bpp.file_owners import actor_from_token, history_on_event
from apps.bpp.models.alternatives import AlternativeOffer, KpiRecord, OfferStatus
from apps.bpp.services.actor import Actor
from apps.bpp.services.core import audit
from apps.bpp.services.core import files as core_files
from apps.files import interface as files

__all__ = ["FILE_TYPE", "HISTORY_CHECKS", "NODE", "OWNER", "register"]

OWNER = "bpp.alternative_offer"
FILE_TYPE = "alternative_offer"
NODE = "bpp.alternatives"

#: Тип журнала → (модель, ``can_view(actor, obj) -> bool`` по пути импорта).
HISTORY_CHECKS = {
    "bpp.alternativeoffer": (AlternativeOffer,
                             "apps.bpp.services.alternatives.read.can_view"),
    "bpp.kpirecord": (KpiRecord, "apps.bpp.services.alternatives.kpi.can_view"),
}


def _offer(owner_id) -> AlternativeOffer | None:
    return AlternativeOffer.objects.filter(pk=owner_id).first()


#: Проверка видимости АП — та же, что у журнала (``read.can_view``).
VIEW_CHECK = HISTORY_CHECKS["bpp.alternativeoffer"][1]


def _can_view(owner_id, token) -> bool:
    offer = _offer(owner_id)
    return offer is not None and import_string(VIEW_CHECK)(actor_from_token(token), offer)


def _can_modify(owner_id, token) -> None:
    offer = _offer(owner_id)
    if offer is None or offer.author_id != token.user_id:
        raise files.FilesForbidden(
            "Менять КП альтернативы может только её автор. Если это ошибка, обратитесь к "
            "администратору.")
    if offer.status != OfferStatus.DRAFT:
        raise files.FilesLocked("КП меняется только в черновике АП.")


def _was_sent(owner_id) -> bool:
    offer = _offer(owner_id)
    return offer is not None and offer.status != OfferStatus.DRAFT


def _lock(owner_id) -> None:
    AlternativeOffer.objects.select_for_update().filter(pk=owner_id).first()


def _history_check(model, path: str):
    """``can_view(request, object_id)`` журнала: ключ не UUID или объекта
    нет — ``False`` (404), иначе — проверка ``path`` над объектом."""
    def check(request, object_id: str) -> bool:
        try:
            key = uuid.UUID(str(object_id))
        except ValueError:
            return False
        obj = model.objects.filter(pk=key).first()
        return obj is not None and import_string(path)(Actor(request), obj)
    return check


def register() -> None:
    files.register_owner(
        OWNER, label="Альтернативное предложение", service="bpp_alternatives", tenant=True,
        folder="alternative-offer", model=AlternativeOffer,
        file_types=(files.FileTypeSpec(FILE_TYPE, max_documents=5, required=True),),
        can_view=_can_view, can_modify=_can_modify, was_sent=_was_sent, lock=_lock,
        on_event=history_on_event(AlternativeOffer),
    )
    core_files.register_owner_type(AlternativeOffer, OWNER)
    for object_type, (model, path) in HISTORY_CHECKS.items():
        audit.register_history_access(object_type, _history_check(model, path))
