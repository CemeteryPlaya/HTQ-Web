"""Chat attachments — порт ``services/messenger/app/api/v1/attachments.py``
+ ``.../services/{attachment_storage,image_thumb,audio_transmux,signed_url}.py``
(attachments-под-задача, PLAN.md §6.5).

Р3 (media.interface): байты хранятся в ``apps.media_files`` через
``apps.media_files.interface.store_file(scope="chat")`` — Django-монолит, не
отдельный сервис, поэтому исходный ``app/services/s3_storage.py`` (свой S3-
клиент) НЕ переносится (тот же принцип, что ``apps/mail/services/
attachment_service.py``/``apps/hr/services/department_file_service.py`` —
единственный разрешённый способ писать байты соседа, apps/core/tests/
test_app_isolation.py). Импорт-исключения media ловятся duck-typing
(``ValueError`` со ``.status_code``/``.detail``) БЕЗ импорта класса
``UploadValidationError``.

Превью (``GET /file/{id}/thumb``) генерируется НАШИМ собственным портом
``image_thumb.py`` (``make_thumbnail`` ниже, ≤256×256 WebP, сохраняет
пропорции), а НЕ через media_files' собственный "variant"-пайплайн
(``apps.media_files.services.image_service.make_variant``): та функция
делает КВАДРАТНЫЙ center-crop для ``thumb_256`` (chat-скоуп несёт
``variants=("thumb_256",)`` в scope_policy.py), что визуально ломает контракт
чата ("превью с сохранением аспекта, чтобы UI зарезервировал место без
прыжка") — использование чужого квадратного variant'а тут было бы
подменой поведения источника, а не портом. Сгенерированный превью-байтес
всё равно проходит через ``interface.store_file()`` ВТОРЫМ отдельным
вызовом (тот же ``scope="chat"``) — просто это НЕ media_files' auto-variant,
а наш собственный upload второго файла.

Побочный эффект (документируется, безвреден): ``store_file(scope="chat")``
для ОРИГИНАЛА картинки сам поставит в очередь ``make_variants`` (chat-скоуп
несёт непустой ``variants``) — тот создаст СВОЙ ``thumb_256`` (квадратный,
неиспользуемый здесь). Лишняя запись ``FileVariant``/лишний объект в
storage, но функционально не мешает: этот модуль никогда не читает
media_files' variant map, только свою собственную вторую загрузку превью.

Внешний signed-URL контракт (``/file/{id}?sig=&exp=``) сохранён БУКВАЛЬНО —
но переиспользует ОБЩИЙ ``htqweb.storage.signed_url`` (тот же HMAC-модуль,
что ``apps.media_files``/``apps.cms``) вместо отдельного секрета исходника
(``attachment_signed_url_secret``): Поток A не вправе трогать
``htqweb/settings`` (см. CLAUDE.md, граница потока), поэтому заводить
отдельную настройку для нового секрета — вне периметра. Функционально
identично: HMAC(resource_id|exp), sig/exp query params, TTL из
``settings.NEWS_SIGNED_URL_TTL``.
"""
from __future__ import annotations

import io
import logging
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from pathlib import PurePosixPath

from PIL import Image, ImageOps, UnidentifiedImageError

from htqweb.storage import signed_query
from htqweb.storage import verify as verify_signed

from apps.messenger.models import ChatAttachment, Room, RoomParticipant

logger = logging.getLogger(__name__)

_SCOPE = "chat"


class NotAParticipant(Exception):
    """403 — вызывающий не участник комнаты."""


class RoomNotFound(Exception):
    """404 — комната не найдена."""


class AttachmentNotFound(Exception):
    """404 — вложение не найдено / физически недоступно."""


class InvalidSignature(Exception):
    """403 — sig/exp не проходят проверку (порт ``verify()`` исходника)."""


class AttachmentUploadRejected(Exception):
    """Пайплайн загрузки media_files отверг файл — оборачивает
    ``ValueError``-совместимый ``UploadValidationError`` соседней аппки
    (status_code/detail) БЕЗ прямого импорта её класса (тот же приём, что
    ``apps/mail/services/attachment_service.py::AttachmentUploadRejected``)."""

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


class AttachmentsNotAvailable(Exception):
    """Порт ``MessengerService.send_message``: один или несколько
    ``attachment_ids`` не резолвятся в комнате/у отправителя. Источник ловит
    это тем же ``except ValueError`` блоком, что и ``NotAParticipant``, и
    ВСЕГДА отвечает 403 (не 400) — см. ``apps/messenger/views.py::
    send_message``."""


class AttachmentAlreadyAttached(Exception):
    """Порт: один или несколько ``attachment_ids`` уже прикреплены к другому
    сообщению. Тот же 403-контракт, что ``AttachmentsNotAvailable`` выше."""


# ── attachment_storage.py (sanitize/classify/keys) — порт verbatim ────────

_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")

_ARCHIVE_EXTENSIONS = {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz"}

_DOCUMENT_EXTENSIONS = {
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt", ".csv",
    ".rtf", ".odt", ".ods", ".odp", ".1c",
}


def sanitize_filename(filename: str | None) -> str:
    """Порт ``attachment_storage.py::sanitize_filename`` verbatim."""
    raw_name = PurePosixPath((filename or "attachment").replace("\\", "/")).name
    cleaned = _SAFE_FILENAME_RE.sub("_", raw_name).strip("._")
    return (cleaned or "attachment")[:180]


def classify_attachment(content_type: str | None, filename: str | None) -> str:
    """Порт ``attachment_storage.py::classify_attachment`` verbatim."""
    mime = (content_type or "").lower()
    suffix = PurePosixPath(filename or "").suffix.lower()

    if mime.startswith("image/"):
        return "images"
    if mime.startswith("audio/"):
        return "audio"
    if mime.startswith("video/"):
        return "video"
    if suffix in _ARCHIVE_EXTENSIONS or mime in {"application/zip", "application/x-rar-compressed"}:
        return "archives"
    if mime.startswith("text/") or suffix in _DOCUMENT_EXTENSIONS:
        return "documents"
    if mime.startswith("application/") and (
        "pdf" in mime
        or "document" in mime
        or "spreadsheet" in mime
        or "presentation" in mime
        or "msword" in mime
        or "officedocument" in mime
    ):
        return "documents"
    return "other"


# ── signed_url.py — переиспользует htqweb.storage.signed_url (см. докстринг
# модуля выше про причину не заводить отдельный секрет) ────────────────────

def _public_url(attachment_id: uuid.UUID) -> str:
    return f"/api/messenger/v1/attachments/file/{attachment_id}?{signed_query(str(attachment_id))}"


def _thumb_public_url(attachment_id: uuid.UUID) -> str:
    return f"/api/messenger/v1/attachments/file/{attachment_id}/thumb?{signed_query(str(attachment_id))}"


# ── audio_transmux.py — порт (sync subprocess, Django-вьюхи синхронны;
# исходник использовал asyncio.create_subprocess_exec под async FastAPI) ───

_WEBM_CONTENT_TYPES = {
    "audio/webm",
    "audio/webm;codecs=opus",
    "audio/webm; codecs=opus",
}


def _has_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


def should_transmux_to_ogg(content_type: str, filename: str) -> bool:
    """Порт ``audio_transmux.py::should_transmux_to_ogg`` verbatim."""
    if not filename.lower().endswith(".ogg"):
        return False
    ct = (content_type or "").lower().replace(" ", "")
    return ct in {c.replace(" ", "") for c in _WEBM_CONTENT_TYPES}


def transmux_webm_to_ogg(buffer: bytes) -> bytes | None:
    """Порт ``audio_transmux.py::transmux_webm_to_ogg`` — ``ffmpeg -c copy``
    (stream copy, без пере-кодирования). Деградация КАК В ИСХОДНИКЕ: если
    ffmpeg не установлен (типично для CI/тестового хоста — см. модульный
    докстринг задачи), возвращает ``None`` и вызывающий (``upload_attachment``
    ниже) оставляет исходный WebM-буфер как есть — той же самой веткой, что
    и исходник ("лучше отдать WebM, чем потерять голосовое сообщение").
    Тесты подменяют ЭТУ функцию (``monkeypatch``) как seam, не полагаясь на
    реальный ffmpeg-бинарь/сеть."""
    if not _has_ffmpeg():
        logger.warning("transmux_skipped: ffmpeg not installed")
        return None

    src_path: str | None = None
    dst_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as src:
            src.write(buffer)
            src_path = src.name
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as dst:
            dst_path = dst.name

        try:
            proc = subprocess.run(
                [
                    "ffmpeg", "-y", "-loglevel", "error", "-i", src_path,
                    "-c:a", "copy", "-map_metadata", "-1", "-f", "ogg", dst_path,
                ],
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=15.0,
            )
        except subprocess.TimeoutExpired:
            logger.warning("transmux_timeout")
            return None

        if proc.returncode != 0:
            logger.warning(
                "transmux_failed code=%s stderr=%s",
                proc.returncode, (proc.stderr or b"").decode(errors="replace")[:200],
            )
            return None

        with open(dst_path, "rb") as f:
            out = f.read()
        return out or None
    finally:
        for p in (src_path, dst_path):
            if p and os.path.exists(p):
                try:
                    os.unlink(p)
                except OSError:
                    pass


# ── image_thumb.py — порт (наша собственная генерация превью, см. докстринг
# модуля выше про причину не использовать media_files' variant-пайплайн) ───

THUMB_MAX_SIDE = 256
THUMB_FORMAT = "WEBP"
THUMB_QUALITY = 80


def make_thumbnail(raw: bytes) -> tuple[bytes | None, int | None, int | None]:
    """Порт ``image_thumb.py::make_thumbnail`` verbatim (EXIF-транспоза,
    ≤256×256, сохранение пропорций, WebP). ``(None, None, None)`` для
    нераспознаваемых/повреждённых изображений (SVG, битые файлы) — тот же
    graceful fallback, что источник."""
    try:
        with Image.open(io.BytesIO(raw)) as src:
            src = ImageOps.exif_transpose(src)
            orig_w, orig_h = src.size

            if orig_w <= THUMB_MAX_SIDE and orig_h <= THUMB_MAX_SIDE and src.format == "WEBP":
                return raw, orig_w, orig_h

            preview = src.copy()
            preview.thumbnail((THUMB_MAX_SIDE, THUMB_MAX_SIDE), Image.Resampling.LANCZOS)
            if preview.mode not in ("RGB", "RGBA"):
                preview = preview.convert("RGBA" if preview.mode in ("LA", "PA") else "RGB")
            out = io.BytesIO()
            preview.save(out, format=THUMB_FORMAT, quality=THUMB_QUALITY, method=4)
            return out.getvalue(), orig_w, orig_h
    except UnidentifiedImageError:
        logger.info("attachment_thumb_unsupported_format")
        return None, None, None
    except Exception as exc:  # noqa: BLE001 — тот же широкий catch, что источник
        logger.warning("attachment_thumb_generation_failed err=%s", exc)
        return None, None, None


# ── upload ──────────────────────────────────────────────────────────────

def upload_attachment(user_id: int, *, room_id: int, upload) -> ChatAttachment:
    """Порт ``attachments.py::upload_attachment``. ``upload`` — Django
    ``UploadedFile`` (``request.FILES["file"]``)."""
    if not RoomParticipant.objects.filter(room_id=room_id, user_id=user_id).exists():
        raise NotAParticipant("Not a participant")

    room = Room.objects.filter(id=room_id).first()
    if room is None:
        raise RoomNotFound("Room not found")

    filename = sanitize_filename(upload.name)
    content_type = upload.content_type or "application/octet-stream"
    buffer = upload.read()

    if should_transmux_to_ogg(content_type, filename):
        repacked = transmux_webm_to_ogg(buffer)
        if repacked is not None:
            buffer = repacked
            content_type = "audio/ogg"

    data_type = classify_attachment(content_type, filename)

    from apps.media_files import interface as media_interface

    try:
        result = media_interface.store_file(
            data=buffer, filename=filename, mime=content_type, scope=_SCOPE, owner_id=user_id,
        )
    except ValueError as exc:
        status_code = getattr(exc, "status_code", 400)
        detail = getattr(exc, "detail", str(exc))
        raise AttachmentUploadRejected(status_code, detail) from exc

    thumbnail_ref: str | None = None
    width: int | None = None
    height: int | None = None
    if data_type == "images":
        thumb_bytes, width, height = make_thumbnail(buffer)
        if thumb_bytes is not None:
            try:
                thumb_result = media_interface.store_file(
                    data=thumb_bytes,
                    filename=f"{filename}.{THUMB_FORMAT.lower()}",
                    mime=f"image/{THUMB_FORMAT.lower()}",
                    scope=_SCOPE,
                    owner_id=user_id,
                )
                thumbnail_ref = str(thumb_result["id"])
            except ValueError:
                # Best-effort — как и в исходнике, сбой генерации/загрузки
                # превью не должен ронять сам upload (thumbnail_path=NULL).
                logger.warning("attachment_thumbnail_upload_failed", exc_info=True)
                thumbnail_ref = None

    attachment = ChatAttachment.objects.create(
        room=room,
        file_metadata_id=result["id"],
        filename=filename,
        content_type=content_type,
        data_type=data_type,
        storage_path=result.get("path"),
        thumbnail_path=thumbnail_ref,
        width=width,
        height=height,
        size=int(result.get("size") or len(buffer)),
        uploaded_by=user_id,
    )
    attachment.public_url = _public_url(attachment.id)
    attachment.save(update_fields=["public_url", "updated_at"])
    return attachment


# ── attach to message (MessengerService.send_message's attachment_ids) ────

def attach_to_message(message, *, attachment_ids: list, room_id: int, sender_id: int) -> None:
    """Порт ``MessengerService.send_message``'s ``attachment_ids`` handling:
    привязывает ранее загруженные (несвязанные) вложения к только что
    созданному сообщению. Требует, что КАЖДЫЙ id резолвится в эту комнату И
    был загружен ИМЕННО отправителем, и что НИ ОДНО из них ещё не прикреплено
    к другому сообщению — иначе исключение (см. классы выше), которое
    вызывающая вьюха превращает в 403 (буквальный контракт источника)."""
    if not attachment_ids:
        return
    attachments = list(
        ChatAttachment.objects.filter(id__in=attachment_ids, room_id=room_id, uploaded_by=sender_id)
    )
    found_ids = {a.id for a in attachments}
    if found_ids != set(attachment_ids):
        raise AttachmentsNotAvailable("One or more attachments are not available for this room")
    if any(a.message_id is not None for a in attachments):
        raise AttachmentAlreadyAttached("One or more attachments are already attached to a message")
    ChatAttachment.objects.filter(id__in=found_ids).update(message=message)


# ── serving (GET /file/{id}, GET /file/{id}/thumb) ────────────────────────

def resolve_attachment_redirect(attachment_id: uuid.UUID, sig: str, exp: int, user_id: int | None) -> str:
    """Порт ``attachments.py::serve_attachment``: проверка sig/exp, затем (если
    есть JWT) — participant-scoping, затем свежий redirect-target через
    ``apps.media_files.interface.get_file_url`` (вместо собственного S3
    presigned — см. докстринг модуля)."""
    if not verify_signed(str(attachment_id), sig, exp):
        raise InvalidSignature("Invalid or expired signature")

    attachment = ChatAttachment.objects.filter(id=attachment_id).first()
    if attachment is None or not attachment.file_metadata_id:
        raise AttachmentNotFound("Attachment not found")

    if user_id is not None and attachment.room_id is not None:
        if not RoomParticipant.objects.filter(room_id=attachment.room_id, user_id=user_id).exists():
            raise NotAParticipant("Not a participant")

    from apps.media_files import interface as media_interface

    url = media_interface.get_file_url(attachment.file_metadata_id)
    if url is None:
        raise AttachmentNotFound("Attachment not found")
    return url


def resolve_attachment_thumb_redirect(attachment_id: uuid.UUID, sig: str, exp: int, user_id: int | None) -> str:
    """Порт ``attachments.py::serve_attachment_thumb``: тот же flow, но
    редиректит на превью; падает обратно на оригинал, когда ``thumbnail_path``
    NULL (не-картинка / сбой генерации / строка до этой под-задачи) — тот же
    fallback-контракт, что источник."""
    if not verify_signed(str(attachment_id), sig, exp):
        raise InvalidSignature("Invalid or expired signature")

    attachment = ChatAttachment.objects.filter(id=attachment_id).first()
    if attachment is None:
        raise AttachmentNotFound("Attachment not found")

    if user_id is not None and attachment.room_id is not None:
        if not RoomParticipant.objects.filter(room_id=attachment.room_id, user_id=user_id).exists():
            raise NotAParticipant("Not a participant")

    target = attachment.thumbnail_path or (
        str(attachment.file_metadata_id) if attachment.file_metadata_id else None
    )
    if not target:
        raise AttachmentNotFound("Attachment not found")

    from apps.media_files import interface as media_interface

    url = media_interface.get_file_url(uuid.UUID(target))
    if url is None:
        raise AttachmentNotFound("Attachment not found")
    return url


# ── serialization (used by views.py + messenger_service.py) ──────────────

def attachment_url(attachment: ChatAttachment) -> str | None:
    """Порт computed_field ``ChatAttachmentRead.url`` — свежая подпись на
    каждую сериализацию (НЕ читает сырую ``public_url`` колонку)."""
    if not attachment.storage_path and not attachment.file_metadata_id:
        return None
    return _public_url(attachment.id)


def attachment_thumbnail_url(attachment: ChatAttachment) -> str | None:
    """Порт computed_field ``ChatAttachmentRead.thumbnail_url`` — ``None``,
    когда ``thumbnail_path`` не заполнен (не-картинка/сбой генерации)."""
    if not attachment.thumbnail_path:
        return None
    return _thumb_public_url(attachment.id)


def serialize_attachment(attachment: ChatAttachment) -> dict:
    """Порт ``ChatAttachmentRead`` — форма ответа, использованная и
    ``/attachments/upload/``, и ``MessageRead.attachments``."""
    return {
        "id": str(attachment.id),
        "room_id": attachment.room_id,
        "message_id": str(attachment.message_id) if attachment.message_id else None,
        "file_metadata_id": str(attachment.file_metadata_id) if attachment.file_metadata_id else None,
        "filename": attachment.filename,
        "size": attachment.size,
        "content_type": attachment.content_type,
        "data_type": attachment.data_type,
        "storage_path": attachment.storage_path,
        "thumbnail_path": attachment.thumbnail_path,
        "width": attachment.width,
        "height": attachment.height,
        "created_at": attachment.created_at.isoformat(),
        "url": attachment_url(attachment),
        "thumbnail_url": attachment_thumbnail_url(attachment),
    }


def attachments_for_messages(message_ids) -> dict:
    """Батч-версия ``serialize_attachment`` для сериализации нескольких
    сообщений разом (без N+1) — та же конвенция, что ``_briefs_by_id`` в
    ``messenger_service.py``."""
    ids = [m for m in message_ids if m is not None]
    if not ids:
        return {}
    rows = list(ChatAttachment.objects.filter(message_id__in=ids).order_by("created_at"))
    out: dict = {}
    for row in rows:
        out.setdefault(row.message_id, []).append(serialize_attachment(row))
    return out
