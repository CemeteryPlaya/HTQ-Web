"""Документы тендерного модуля — владельцы файлов платформенной ``apps.files``.

Зовётся из ``TenderConfig.ready()``. Одна файловая подсистема на платформу:
файлы лежат в ``apps.files``, видны на её панели
``/api/files/v1/<владелец>/<id>/files/`` и журналируются там же (образец —
``apps/bpp/file_owners.py``).

``tender.request`` — ТЗ и чертежи заявки (T1.1; план этапов 0–2, §3.4): тип
``tender_spec`` (миграция ``files/0006_tender_file_types``), до 20 документов.
Видит файлы тот, кто видит заявку; добавляет, удаляет и версионирует — автор
в «Черновике» и «На доработке». Права — правила самой заявки
(``services/requests/crud.py``), без второй копии.

``tender.offer`` — файлы коммерческого предложения поставщика (T3.4; план
этапа 3, §2 T3.4): тип ``tender_offer`` (миграция
``files/0007_tender_offer_type``), до 10 документов на предложение (версию).
Прикладывает и удаляет их только портал — из кода (``attach_bytes``,
``remove_document``, ``services/portal/files.py``), автор — служебная учётка
``tender-portal``. На панели ``/api/files/v1`` сотрудники до вскрытия
предложений (этап 5) файлов КП не видят — никто, кроме суперпользователя, —
и не меняют вовсе. Отправленная версия — «отправлялась»: её файлы
физически не удаляются.
"""

from __future__ import annotations

from apps.files import interface as files
from apps.tender.models import Offer, TenderRequest
from apps.tender.services.core import audit
from apps.tender.services.requests import crud

REQUEST_OWNER = crud.FILE_OWNER
OFFER_OWNER = "tender.offer"

#: Событие файловой подсистемы → запись журнала заявки. Скачивания туда не
#: пишутся: их журнал — ``FileEvent`` подсистемы.
_AUDIT_ACTIONS = {
    "file_attached": "file_attached",
    "file_version_attached": "file_replaced",
    "file_deleted": "file_deleted",
}


def _request(owner_id) -> TenderRequest | None:
    return TenderRequest.objects.filter(pk=owner_id).first()


def _can_view(owner_id, token) -> bool:
    req = _request(owner_id)
    if req is None:
        return False
    ctx = crud.Ctx.from_token(token)
    return ctx.can(crud.NODE, "view") and crud.can_view(ctx, req)


def _can_modify(owner_id, token) -> None:
    req = _request(owner_id)
    if req is None or req.author_id != token.user_id:
        raise files.FilesForbidden(
            "Менять документы заявки может только её автор. Если это ошибка, "
            "обратитесь к администратору.")
    if req.status not in crud.EDITABLE:
        raise files.FilesLocked(
            f"Документы заявки {req.number} меняются только в статусах «Черновик» и "
            f"«На доработке».")


def _was_sent(owner_id) -> bool:
    req = _request(owner_id)
    return req is not None and crud.was_sent(req)


def _lock(owner_id) -> None:
    TenderRequest.objects.select_for_update().filter(pk=owner_id).first()


def _on_event(owner_id, event: str, actor_id: int | None, payload: dict) -> None:
    action = _AUDIT_ACTIONS.get(event)
    if action is None:
        return
    changes = {"file_type": payload.get("file_type"), "filename": payload.get("name")}
    if payload.get("file_id") is not None:
        changes["file"] = str(payload["file_id"])
    if event == "file_version_attached":
        changes["previous"] = str(payload.get("replaced_file_id"))
        changes["version"] = payload.get("version_no")
    audit.record_for(crud.OBJECT_TYPE, str(owner_id), action, actor_id=actor_id,
                     changes=changes)


# ── файлы КП поставщика (T3.4) ──────────────────────────────────────────

def _offer_can_view(owner_id, token) -> bool:
    """До вскрытия (этап 5) — только суперпользователь: цены и КП участников
    закрыты от всех до срока (ТЗ TND-020)."""
    return bool(getattr(token, "is_superuser", False))


def _offer_can_modify(owner_id, token) -> None:
    raise files.FilesForbidden(
        "Файлы коммерческого предложения прикладывает и удаляет поставщик на портале.")


def _offer_was_sent(owner_id) -> bool:
    return Offer.objects.filter(pk=owner_id, number__isnull=False).exists()


def _offer_lock(owner_id) -> None:
    Offer.objects.select_for_update().filter(pk=owner_id).first()


def register() -> None:
    files.register_owner(
        OFFER_OWNER, label="Предложение поставщика (тендер)", service="tender",
        tenant=True, folder="tender-offer", model=Offer,
        # КП: PDF, DOCX, XLSX, JPG, PNG до 20 МБ, до 10 документов на версию.
        file_types=(files.FileTypeSpec("tender_offer", max_documents=10),),
        can_view=_offer_can_view, can_modify=_offer_can_modify,
        was_sent=_offer_was_sent, lock=_offer_lock,
    )
    files.register_owner(
        REQUEST_OWNER, label="Заявка (тендер)", service="tender", tenant=True,
        folder="tender-request", model=TenderRequest,
        # ТЗ и чертежи: PDF, DOCX, XLSX, JPG, PNG до 20 МБ, до 20 документов
        # на заявку; версии в предел не входят.
        file_types=(files.FileTypeSpec("tender_spec", quota_group="documents"),),
        quotas={"documents": 20},
        can_view=_can_view, can_modify=_can_modify, was_sent=_was_sent, lock=_lock,
        on_event=_on_event,
    )
