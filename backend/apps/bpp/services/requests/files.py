"""Документы заявки — КП, ТЗ, спецификация, прочее (ТЗ §7.5, §21; B2.2).

Хранение, версии, лимиты и журнал скачиваний — платформенная ``apps.files``
через обёртку модуля (``services/core/files.py``), тип файла
``request_attachment``: PDF, DOCX, XLSX, JPG, PNG до 20 МБ, до 20
документов (владелец ``bpp.purchase_request`` — ``apps/bpp/file_owners.py``).
Здесь — кто и когда:

- добавить документ — автор, пока заявка в черновике или на доработке;
- новая версия — автор в любом статусе, кроме финальных: после отправки
  документ не удаляется, а заменяется версией (ТЗ §21);
- список и ссылку на скачивание получает тот, кто видит заявку.

Удаление документа — на панели файлов ``/api/files/v1`` (автор, в черновике
и на доработке; после первой отправки — только пометкой).
"""

from __future__ import annotations

from apps.bpp.models import PurchaseRequest, RequestStatus
from apps.bpp.services.actor import Actor
from apps.bpp.services.core import files as core_files
from htqweb.errors import DomainError

from . import requests as service

FILE_TYPE = "request_attachment"
FINAL = (RequestStatus.REJECTED, RequestStatus.CANCELLED, RequestStatus.CLOSED)


def _upload(upload) -> tuple[bytes, str, str]:
    if upload is None:
        raise DomainError("E-VAL-01", "Выберите файл.",
                          fields=[{"field": "file", "message": "Нет файла"}])
    return upload.read(), upload.name, upload.content_type or "application/octet-stream"


def _own_file(req: PurchaseRequest, file_id) -> dict:
    row = core_files.get_file(req, file_id)
    if row is None:
        raise DomainError("E-NOT-FOUND", "Файл не найден.", status=404)
    return row


def list_files(actor: Actor, request_id) -> list[dict]:
    return core_files.list_files(service.get_visible(actor, request_id))


def attach(actor: Actor, request_id, upload) -> dict:
    req = service.get_visible(actor, request_id)
    service._require_author(actor, req, "Прикладывать документы к")
    service._require_status(req, service.EDITABLE, "добавление документа")
    data, name, mime = _upload(upload)
    return core_files.attach(req, FILE_TYPE, data=data, filename=name, mime=mime,
                             actor_id=actor.user_id, request=actor.request)


def replace(actor: Actor, request_id, file_id, upload) -> dict:
    req = service.get_visible(actor, request_id)
    service._require_author(actor, req, "Заменять документы")
    if req.status in FINAL:
        service._require_status(req, (), "замена документа")
    old = _own_file(req, file_id)
    if old["replaced"]:
        raise DomainError("E-CON-01", "Эта версия файла уже заменена — обновите страницу.",
                          status=409)
    data, name, mime = _upload(upload)
    return core_files.replace(old["id"], data=data, filename=name, mime=mime,
                              actor_id=actor.user_id, request=actor.request)


def link(actor: Actor, request_id, file_id) -> dict:
    req = service.get_visible(actor, request_id)
    row = _own_file(req, file_id)
    return {"url": core_files.download_url(row["id"], user_id=actor.user_id,
                                           request=actor.request)}
