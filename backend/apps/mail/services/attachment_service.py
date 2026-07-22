"""Вложения писем — байты хранятся через ``apps.media_files.interface``
(``store_file``/``get_file_url``/``delete_file``), НЕ через отдельный
``s3_storage.py``-подобный копию и НЕ через httpx-проксирование к media
как отдельному сервису (Р3 брифа mail-messages) — в этом Django-монолите
media — сосед по процессу, доступный только через его ``interface``
(apps/core/tests/test_app_isolation.py).

Странность исходника: ``services/email/app/services/s3_storage.py``
существует как готовая S3/local-storage-абстракция, но НИ ОДИН роутер
исходника (``emails.py::send_email`` игнорирует ``attachment_ids``;
``services/sync/mapper.py::replace_attachments`` никогда не заполняет
``file_metadata_id`` — ни один из трёх sync-драйверов не выставляет этот
ключ в словаре вложения) на самом деле не сохраняет байты вложений —
``EmailAttachment`` там всегда metadata-only (см. ``mime.py`` докстринг:
"Attachment upload-on-send is a Phase 9 follow-up"). Живого HTTP-эндпойнта
загрузки вложения в исходнике НЕТ вовсе.

Эта функция — заранее подготовленный сеам для будущей под-задачи (compose
upload UI / Phase 9 исходника, либо sync-под-задачи, когда она начнёт
реально скачивать байты у провайдера) — используется тестами напрямую, не
проводом ни одного из 6 эндпойнтов emails.py (ни один из них байты вложений
не принимает).

Scope — ``generic`` (не ``hr_doc``/``hr_department``/``task_attachment`` —
mail не входит в ``RESTRICTED_SCOPES`` media_files/services/scope_policy.py,
письма — произвольные mime-типы, приватные по умолчанию, что подходит под
``generic``: не публичный, без ограничения по mime).
"""
from __future__ import annotations

from apps.mail.models import EmailAttachment, EmailMessage

_SCOPE = "generic"


class AttachmentUploadRejected(Exception):
    """Пайплайн загрузки media_files отверг файл — оборачивает
    ``UploadValidationError``-совместимый ``ValueError`` соседней аппки
    (status_code/detail) БЕЗ прямого импорта её класса (тот же приём, что
    apps/hr/services/department_file_service.py::UploadRejected — прямой
    импорт чего-либо, кроме ``apps.media_files.interface``, ловится
    apps/core/tests/test_app_isolation.py)."""

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


def store_attachment(
    message: EmailMessage, *, data: bytes, filename: str, mime: str,
    owner_id: int | None, content_id: str | None = None,
) -> EmailAttachment:
    """Загружает байты через ``apps.media_files.interface.store_file`` и
    создаёт ``EmailAttachment`` со ссылкой на результат (``file_metadata_id``
    — реальный ``FileMetadata.id``, не ``None``, как это было бы при
    буквальном 1:1 переносе dead-кода исходника). Помечает
    ``message.has_attachments = True``."""
    from apps.media_files import interface as media_interface

    try:
        result = media_interface.store_file(
            data=data,
            filename=filename or "attachment.bin",
            mime=mime or "application/octet-stream",
            scope=_SCOPE,
            owner_id=owner_id,
        )
    except ValueError as exc:
        status_code = getattr(exc, "status_code", 400)
        detail = getattr(exc, "detail", str(exc))
        raise AttachmentUploadRejected(status_code, detail) from exc

    attachment = EmailAttachment.objects.create(
        message=message,
        file_metadata_id=result["id"],
        filename=result.get("original_filename") or filename or "attachment.bin",
        mime_type=result.get("mime") or mime or "application/octet-stream",
        size=int(result.get("size") or 0),
        content_id=content_id,
    )
    if not message.has_attachments:
        message.has_attachments = True
        message.save(update_fields=["has_attachments", "updated_at"])
    return attachment


def attachment_url(attachment: EmailAttachment) -> str | None:
    """URL вложения через ``media_interface.get_file_url`` — ``None``, если
    ``file_metadata_id`` не задан (чисто metadata-only строка — sync-путь
    исходника, см. модуль docstring) или файл не резолвится."""
    if attachment.file_metadata_id is None:
        return None
    from apps.media_files import interface as media_interface

    return media_interface.get_file_url(attachment.file_metadata_id)
