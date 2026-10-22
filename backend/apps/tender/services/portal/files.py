"""Файлы коммерческого предложения на портале (T3.4; план этапа 3, §1, §2 T3.4).

Владелец — ``tender.offer`` (``file_owners.py``): файлы привязаны к строке
предложения. Портал работает с файлами ТЕКУЩЕГО предложения (черновик, а
без него — последняя версия): список; загрузка и удаление — только в
черновике (нет его — заводится копия последней версии вместе с файлами,
``offers.get_draft``). «Отправить» превращает черновик в версию — файлы
остаются у неё и физически больше не удаляются.

**Загрузка только при включённом антивирусе** (``htqweb.antivirus.enabled()``):
портал анонимный, и непроверенный файл от постороннего в хранилище не
попадает — без сканера 503 ``E-SYS-01``. Срок и статус тендера — как у правки
предложения (409 ``E-TND-05``). Лимит 30 загрузок в час на приглашение —
у ручки (``htqweb.ratelimit``). Ответы — белым списком.
"""

from __future__ import annotations

from collections.abc import Callable

from django.db import transaction

from apps.files import interface as files
from apps.tender.models import Invitation
from htqweb import antivirus
from htqweb.errors import DomainError

from . import offers
from .actor import portal_actor

Event = Callable[[str, dict], None]


def _out(row: dict) -> dict:
    """Документ для поставщика — только перечисленные ключи."""
    return {"id": str(row["document_id"]), "name": row["name"], "size": row["size"],
            "mime": row["mime"], "uploaded_at": row["uploaded_at"]}


def list_files(ctx) -> list[dict]:
    inv = Invitation.objects.get(pk=ctx.invitation.pk)
    offer = offers._current(inv)
    if offer is None:
        return []
    return [_out(row) for row in files.current_files(offers.OFFER_OWNER, offer.pk,
                                                     offers.OFFER_FILE_TYPE)]


def _files_error(exc) -> DomainError:
    """Отказ подсистемы файлов — тем же кодом, статусом и текстом ТЗ."""
    return DomainError(exc.code, exc.message, fields=list(exc.fields), status=exc.status,
                       details=dict(exc.details) if exc.details else None)


def scanner_required() -> None:
    if not antivirus.enabled():
        raise DomainError("E-SYS-01", "Загрузка файлов временно недоступна. Повторите "
                                      "позже или обратитесь к закупщику.", status=503)


def upload(ctx, *, data: bytes, filename: str, mime: str, ip: str | None,
           user_agent: str | None, event: Callable[[str, dict], None]) -> dict:
    """Приложить файл к черновику. Сканер выключен — 503 ``E-SYS-01``; угроза —
    422 ``E-FIL-08``, формат/размер/квота — отказ подсистемы (422).

    Отказ подсистемы ловится ВНУТРИ транзакции и поднимается после неё: её
    запись об отказе (``FileEvent`` ``file_rejected`` с IP) должна остаться в
    журнале, а не откатиться вместе с ответом 422."""
    scanner_required()
    offers.prepare_draft(ctx, check=False)
    refused = None
    with transaction.atomic():
        tender, inv = offers._lock(ctx)
        draft = offers.get_draft(inv, tender)
        try:
            row = files.attach_bytes(offers.OFFER_OWNER, draft.pk,
                                     file_type=offers.OFFER_FILE_TYPE, data=data,
                                     filename=filename, mime=mime, actor_id=portal_actor(),
                                     ip=ip, user_agent=user_agent)
        except files.FilesError as exc:
            refused = exc
        else:
            event("file_uploaded", {"offer_id": str(draft.pk),
                                    "document_id": row["document_id"],
                                    "name": row["name"], "size": row["size"]})
    if refused is not None:
        raise _files_error(refused) from refused
    return _out(row)


def remove(ctx, document_id, *, ip: str | None, user_agent: str | None,
           event: Callable[[str, dict], None]) -> None:
    """Удалить файл черновика (своего приглашения); чужой или несуществующий —
    404. Документ отправленной версии удаляется из черновика-копии: у самой
    версии он остаётся. Копию заводит ``prepare_draft`` своей транзакцией —
    отказ 404 не оставляет в хранилище скопированных байтов."""
    offers.prepare_draft(ctx, check=False)
    with transaction.atomic():
        _remove(ctx, document_id, ip=ip, user_agent=user_agent, event=event)


def _remove(ctx, document_id, *, ip: str | None, user_agent: str | None,
            event: Callable[[str, dict], None]) -> None:
    tender, inv = offers._lock(ctx)
    draft = offers.get_draft(inv, tender)
    document_id = offers.draft_document_id(draft, inv, document_id)
    try:
        files.remove_document(offers.OFFER_OWNER, draft.pk, document_id,
                              actor_id=portal_actor(), ip=ip, user_agent=user_agent)
    except files.FilesError as exc:
        raise _files_error(exc) from exc
    event("file_removed", {"offer_id": str(draft.pk), "document_id": str(document_id)})
