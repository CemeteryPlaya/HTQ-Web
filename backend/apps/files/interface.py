"""Публичный API файловой подсистемы для ДРУГИХ аппок.

Владелец документов (заявка, договор, …) регистрируется здесь из своего
``AppConfig.ready()`` и дальше спрашивает о своих файлах только через этот
модуль — прямой импорт ``apps.files.models``/``services`` из другой аппки
ловится ``apps/core/tests/test_app_isolation.py``.

``register_owner`` и классы правил (``FileTypeSpec``, ``FilesForbidden``,
``FilesLocked``) — без ``require_service``: регистрация идёт при запуске, и
выключенная подсистема не должна ронять платформу. Так же без него
``assign_company`` — шаг ``tenancy_bootstrap``, который обязан пройти при
любом состоянии рубильника. Остальные функции начинаются с
``require_service("files")``, как в любой аппке.
"""

from __future__ import annotations

from typing import Any

from apps.core.services import require_service

from .errors import E_REQUIRED, FilesError, envelope
from .models import FileObject, FileType
from .services import documents
from .services.documents import owner_company
from .services.registry import (
    MULTI, SINGLE, FilesForbidden, FilesLocked, FileTypeSpec, get_owner,
    register_owner,
)

__all__ = [
    "MULTI", "SINGLE", "FileTypeSpec", "FilesError", "FilesForbidden", "FilesLocked",
    "register_owner", "live_document_count", "missing_required",
    "required_files_error", "owners_with_documents", "owner_deleted",
    "adopt_media_file", "assign_company", "current_files",
    "attach_bytes", "replace_bytes", "download_link", "find_version",
]


def live_document_count(owner_type: str, owner_id: Any,
                        file_type: str | None = None) -> int:
    """Сколько у объекта действующих (не удалённых) документов, версии не в счёт."""
    require_service("files")
    entry = get_owner(owner_type)
    qs = FileObject.objects.filter(owner_type=owner_type,
                                   owner_id=entry.storage_id(owner_id),
                                   deleted_at__isnull=True)
    if entry.tenant:
        qs = qs.filter(company_slug=owner_company(entry))
    if file_type is not None:
        qs = qs.filter(file_type_id=file_type)
    return qs.values("document_id").distinct().count()


def missing_required(owner_type: str, owner_id: Any) -> list[dict]:
    """Обязательные типы, по которым нет ни одного действующего документа:
    ``[{"code", "name"}]``. Владелец зовёт это в своём переходе «Отправить»
    — под своей блокировкой, — и сам решает, отказывать ли."""
    require_service("files")
    entry = get_owner(owner_type)
    required = [spec.code for spec in entry.file_types if spec.required]
    if not required:
        return []
    names = dict(FileType.objects.filter(code__in=required).values_list("code", "name"))
    return [{"code": code, "name": names.get(code, code)} for code in required
            if live_document_count(owner_type, owner_id, code) == 0]


def required_files_error(missing: list[dict], *, action: str) -> dict:
    """Тело 422 ``E-FIL-04`` в формате ТЗ для отказа владельца.

    ``action`` — что не удалось, в инфинитиве: «отправить договор».
    """
    names = ", ".join(f"«{item['name']}»" for item in missing)
    what = f"файл {names}" if len(missing) == 1 else f"файлы {names}"
    verb = "приложен" if len(missing) == 1 else "приложены"
    message = (f"Не удалось {action}: не {verb} {what}. Приложите "
               f"{'его' if len(missing) == 1 else 'их'} и повторите отправку.")
    return envelope(
        E_REQUIRED, message,
        fields=[{"field": item["code"], "message": "Не приложен обязательный файл"}
                for item in missing],
        details={"missing": missing})


def owners_with_documents(owner_type: str, owner_ids,
                          file_type: str | None = None) -> set:
    """Какие из объектов (id) имеют хоть один действующий документ этого типа
    — одним запросом на весь список (отметка «файл приложен» в реестре).
    Ключи — в типе ключа модели владельца."""
    return documents.owners_with_documents(owner_type, owner_ids, file_type)


def owner_deleted(owner_type: str, owner_id: Any, *, actor_id: int | None = None) -> None:
    """Владелец удаляет свой объект. Зовётся в ЕГО транзакции удаления и ДО
    удаления строки: ни разу не отправленный объект уносит файлы физически,
    отправлявшийся оставляет их помеченными удалёнными (ТЗ §21)."""
    documents.purge_owner(documents.owner_ref(owner_type, owner_id), actor_id)


def adopt_media_file(owner_type: str, owner_id: Any, *, file_type: str,
                     media_file_id: str, uploaded_by_id: int | None = None) -> dict:
    """Перенос уже сохранённого в media файла (старое поле владельца) в его
    папку версией 1 нового документа — для команд миграции данных.
    Повтор с тем же файлом ничего не создаёт. ``{"file_id", "document_id",
    "created"}``; отказ квоты — ``FilesError``, отказ media — его ошибка."""
    row, created = documents.adopt(
        documents.owner_ref(owner_type, owner_id), file_type=file_type,
        media_file_id=media_file_id, uploaded_by_id=uploaded_by_id)
    return {"file_id": row.pk, "document_id": str(row.document_id), "created": created}


def assign_company(slug: str, *, dry_run: bool = False) -> dict:
    """``tenancy_bootstrap``: проставить компанию файлам тенантных владельцев,
    заведённым до первой компании. ``{"files": n, "events": m}``."""
    return documents.assign_company(slug, dry_run=dry_run)


def current_files(owner_type: str, owner_id: Any, file_type: str | None = None) -> list[dict]:
    """Действующие версии живых документов объекта — для владельца, который
    показывает свои документы (список файлов в карточке) или переносит их в
    другой объект (КП выбранной альтернативы — в приложения нового
    договора). Элемент — карточка версии, как в папке (``id``,
    ``document_id``, ``file_type``, ``version_no``, ``name``, ``mime``,
    ``size``, ``sha256``, ``uploaded_by_id``, ``uploaded_at``, …), плюс
    ``media_file_id``; порядок — по времени загрузки."""
    require_service("files")
    entry = get_owner(owner_type)
    qs = FileObject.objects.filter(owner_type=owner_type,
                                   owner_id=entry.storage_id(owner_id),
                                   deleted_at__isnull=True, is_replaced=False)
    if entry.tenant:
        qs = qs.filter(company_slug=owner_company(entry))
    if file_type is not None:
        qs = qs.filter(file_type_id=file_type)
    return [{**documents.version_out(row), "media_file_id": row.media_file_id}
            for row in qs.order_by("uploaded_at", "id")]


# ── загрузка и скачивание из кода владельца ─────────────────────────────
#
# Для владельца, который принимает файл своей ручкой (заявка БЗО, авансовый
# отчёт) и хранит его здесь. Проверки — те же, что у HTTP-загрузки
# ``/api/files/v1``: справочник форматов и размеров, квоты владельца под его
# блокировкой, антивирус, версии, журнал ``FileEvent``. Права на объект НЕ
# проверяются — их проверил вызывающий владелец (см. ``services/documents.py``,
# раздел «загрузка и скачивание из кода владельца»). Отказ — ``FilesError`` с
# кодом и текстом ТЗ (конверт D-28, ``FilesError.body()``).

def attach_bytes(owner_type: str, owner_id: Any, *, file_type: str, data: bytes,
                 filename: str, mime: str, actor_id: int,
                 ip: str | None = None, user_agent: str | None = None) -> dict:
    """Версия 1 нового документа типа ``file_type`` — карточка версии, как в
    папке. ``mime`` — подсказка для имени без расширения: тип файла
    подсистема определяет по расширению, а media сверяет с ним содержимое."""
    require_service("files")
    row = documents.upload_bytes(
        documents.owner_ref(owner_type, owner_id), actor_id=actor_id, data=data,
        filename=filename, mime=mime, file_type=file_type,
        audit={"ip": ip or "", "user_agent": user_agent or ""})
    return documents.version_out(row)


def replace_bytes(owner_type: str, owner_id: Any, document_id, *, data: bytes,
                  filename: str, mime: str, actor_id: int, base_file_id=None,
                  ip: str | None = None, user_agent: str | None = None) -> dict:
    """Новая версия документа ``document_id``. ``base_file_id`` — поверх какой
    версии: уже заменённая — 409 ``E-CON-01``; без него — поверх действующей."""
    require_service("files")
    row = documents.upload_bytes(
        documents.owner_ref(owner_type, owner_id), actor_id=actor_id, data=data,
        filename=filename, mime=mime, document_id=document_id,
        base_file_id=base_file_id,
        audit={"ip": ip or "", "user_agent": user_agent or ""})
    return documents.version_out(row)


def download_link(owner_type: str, owner_id: Any, document_id, *, actor_id: int | None,
                  ip: str | None = None, user_agent: str | None = None,
                  file_id=None) -> str:
    """Временная ссылка на скачивание — версии ``file_id`` или действующей.
    Каждая выдача пишет ``file_downloaded`` (кто, IP, user-agent) в журнал
    (ТЗ §25.2): других путей к байтам у файлов подсистемы нет."""
    require_service("files")
    link = documents.link_for(
        documents.owner_ref(owner_type, owner_id), document_id, actor_id=actor_id,
        file_id=file_id, audit={"ip": ip or "", "user_agent": user_agent or ""})
    return link["url"]


def find_version(file_id) -> dict | None:
    """Карточка версии по её id вместе с владельцем (``owner_type``,
    ``owner_id`` — ключ строкой, как в таблице). ``None`` — нет такой
    версии в компании запроса или её владелец не зарегистрирован. Для
    владельца, чей API адресует файл id версии, а не парой «документ +
    версия»."""
    require_service("files")
    return documents.find_version(file_id)
