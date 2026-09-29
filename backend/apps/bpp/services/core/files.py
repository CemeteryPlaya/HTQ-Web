"""Файлы документов модуля — тонкая обёртка над платформенной ``apps.files``.

Одна файловая подсистема на платформу (решение 28.09, план этапа 2 A,
задача 1): байты, версии, квоты, форматы и размеры, антивирус и журнал
файловых операций (``FileEvent``: загрузка, версия, скачивание — кто, IP,
user-agent) — в ``apps.files``. Документы модуля — её владельцы,
зарегистрированные в ``apps/bpp/file_owners.py`` и в
``services/<подмодуль>/file_owner.py`` подмодулей (подключаются сами);
там же правила ТЗ §21 (``FileTypeSpec``), а форматы и размеры — в
справочнике «Типы файлов» (миграции ``files/0003_bpp_file_types`` и
``files/0004_bpp_stage3_file_types``).

Здесь — прежние функции модуля с прежними сигнатурами, чтобы заявка и
подотчёт звали их как раньше:

- ``attach(owner, file_type, *, data, filename, mime, actor_id)`` — новый документ;
- ``replace(file_id, *, data, filename, mime, actor_id)`` — новая версия поверх
  версии ``file_id``;
- ``list_files(owner)`` — действующие версии живых документов;
- ``download_url(file_id, *, user_id)`` — ссылка через журнал скачиваний;
- ``get_file(owner, file_id)`` — версия этого документа или ``None``.

Права на документ проверяет вызывающий сервис документа — подсистема при
загрузке из кода их не спрашивает. Отказ подсистемы (``FilesError``) —
``FilesDomainError``: код и текст ``apps.files`` (``E-FIL-01`` формат 415,
``E-FIL-02`` размер 413, ``E-FIL-03`` предел количества 409, ``E-FIL-08``
угроза 422, ``E-SYS-01`` антивирус молчит 503, ``E-CON-01`` версию уже
заменили 409), а не прежние ``E-FILE-*``: коды одни на ручку модуля и на
панель ``/api/files/v1``.

Карточка файла — прежняя форма (``id``, ``file_type``, ``filename``, ``mime``,
``size``, ``sha256``, ``version``, ``replaced``, ``uploaded_by``,
``uploaded_at``) плюс ``document_id``. ``id`` — id версии в ``apps.files``
строкой.
"""

from __future__ import annotations

from apps.core.infrastructure import client_ip
from apps.files import interface as files
from htqweb.errors import DomainError

#: Модель документа (``_meta.label_lower``) → владелец в ``apps.files``.
#: Заполняют ``apps/bpp/file_owners.py::register`` и ``register()`` модулей
#: ``services/<подмодуль>/file_owner.py`` при запуске.
_OWNER_TYPES: dict[str, str] = {}


class FilesDomainError(DomainError):
    """Отказ файловой подсистемы в конверте модуля — вместе с ``details``
    (сколько документов из скольких, какие форматы): ``DomainError`` их не
    несёт, а интерфейсу они нужны так же, как на панели ``/api/files/v1``."""

    def __init__(self, exc: files.FilesError) -> None:
        super().__init__(exc.code, exc.message, fields=exc.fields, status=exc.status)
        self.details = exc.details

    def payload(self) -> dict:
        return {**super().payload(), "details": self.details}


def register_owner_type(model, owner_type: str) -> None:
    """Документы модели ``model`` хранятся у владельца ``owner_type``."""
    _OWNER_TYPES[model._meta.label_lower] = owner_type


def owner_type_of(owner) -> str:
    try:
        return _OWNER_TYPES[owner._meta.label_lower]
    except KeyError:
        raise LookupError(
            f"{owner._meta.label_lower}: документ не зарегистрирован владельцем файлов — "
            f"нужен register_owner_type(<Модель>, <владелец>) в apps/bpp/file_owners.py "
            f"или в register() модуля services/<подмодуль>/file_owner.py") from None


def _serialize(version: dict) -> dict:
    return {
        "id": str(version["id"]),
        "document_id": version["document_id"],
        "file_type": version["file_type"],
        "filename": version["name"],
        "mime": version["mime"],
        "size": version["size"],
        "sha256": version["sha256"],
        "version": version["version_no"],
        "replaced": version["is_replaced"],
        "uploaded_by": version["uploaded_by_id"],
        "uploaded_at": version["uploaded_at"],
    }


def _not_found() -> DomainError:
    return DomainError("E-NOT-FOUND", "Файл не найден. Обновите страницу.", status=404)


def _audit(request) -> dict:
    """IP и user-agent для журнала скачиваний (ТЗ §25.2) — если под рукой
    запрос; без него строка журнала пишется без них."""
    if request is None:
        return {}
    return {"ip": client_ip(request) or "",
            "user_agent": request.META.get("HTTP_USER_AGENT", "")[:300]}


def attach(owner, file_type: str, *, data: bytes, filename: str, mime: str,
           actor_id: int, request=None) -> dict:
    try:
        version = files.attach_bytes(owner_type_of(owner), owner.pk, file_type=file_type,
                                     data=data, filename=filename, mime=mime,
                                     actor_id=actor_id, **_audit(request))
    except files.FilesError as exc:
        raise FilesDomainError(exc) from exc
    return _serialize(version)


def replace(file_id: str, *, data: bytes, filename: str, mime: str, actor_id: int,
            request=None) -> dict:
    """Новая версия поверх версии ``file_id``: если её уже заменили —
    409 ``E-CON-01`` с тем, кто успел раньше."""
    old = files.find_version(file_id)
    if old is None:
        raise _not_found()
    try:
        version = files.replace_bytes(old["owner_type"], old["owner_id"], old["document_id"],
                                      data=data, filename=filename, mime=mime,
                                      actor_id=actor_id, base_file_id=old["id"],
                                      **_audit(request))
    except files.FilesError as exc:
        raise FilesDomainError(exc) from exc
    return _serialize(version)


def list_files(owner) -> list[dict]:
    return [_serialize(v) for v in files.current_files(owner_type_of(owner), owner.pk)]


def get_file(owner, file_id) -> dict | None:
    """Версия ``file_id``, если она принадлежит этому документу (в том числе
    уже заменённая), иначе ``None``."""
    version = files.find_version(file_id)
    if version is None or version["owner_type"] != owner_type_of(owner) \
            or version["owner_id"] != str(owner.pk):
        return None
    return _serialize(version)


def owner_deleted(owner, *, actor_id: int | None) -> None:
    """Документ удаляется — что станет с его файлами (ТЗ §21): у ни разу не
    отправленного они удаляются физически, у отправлявшегося остаются с
    пометкой. Звать в транзакции удаления и ДО удаления строки документа."""
    files.owner_deleted(owner_type_of(owner), owner.pk, actor_id=actor_id)


def download_url(file_id: str, *, user_id: int, request=None) -> str:
    """Ссылка на версию ``file_id``; выдача пишется в журнал файловых
    операций (кто, а с ``request`` — ещё IP и user-agent).

    ⚠️ Права здесь НЕ проверяются — ни на документ, ни на тип файла.
    Путь «из кода» (``apps.files.interface.download_link``, как и
    ``attach_bytes``/``replace_bytes`` у загрузки) доверяет проверкам
    владельца и для загрузки, и для скачивания: колбэки ``can_view`` и
    ``can_view_type`` владельца подсистема применяет только на своих
    ручках ``/api/files/v1`` (по токену), а сюда токен не приходит. Поэтому
    вызывающий сервис документа до вызова сам убеждается, что человек
    видит документ, а владелец с видимостью по типу файла (зарегистрирован
    с ``can_view_type``) — ещё и что он видит тип этой версии
    (``get_file(owner, file_id)["file_type"]``): иначе ссылка откроет файл
    типа, который панель документов этому человеку не показывает."""
    version = files.find_version(file_id)
    if version is None:
        raise _not_found()
    try:
        return files.download_link(version["owner_type"], version["owner_id"],
                                   version["document_id"], actor_id=user_id,
                                   file_id=version["id"], **_audit(request))
    except files.FilesError as exc:
        raise FilesDomainError(exc) from exc
