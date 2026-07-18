"""Helpers for uploading chat attachments to S3.

Layout (per ``services/README.md`` — bucket ``htqweb-messenger``)::

    chats/<room_storage_key>/<data_type>/<attachment_id>_<filename>
    chats/<room_storage_key>/metadata/<attachment_id>.json
    chats/<room_storage_key>/history/<YYYY>/<MM>/<DD>.jsonl   (weekly archive)

The data file is streamed to S3 in 1 MiB chunks accumulated in memory; the
JSON metadata snapshot is written immediately after so admin tools and the
weekly history archive can read attachments without touching Postgres.
"""

from __future__ import annotations

import json
import re
import uuid
from pathlib import PurePosixPath
from typing import Any

from fastapi import UploadFile

from app.services.s3_storage import Storage, get_storage

_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")

_ARCHIVE_EXTENSIONS = {
    ".zip",
    ".rar",
    ".7z",
    ".tar",
    ".gz",
    ".bz2",
    ".xz",
}

_DOCUMENT_EXTENSIONS = {
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    ".txt",
    ".csv",
    ".rtf",
    ".odt",
    ".ods",
    ".odp",
    ".1c",
}


def sanitize_filename(filename: str | None) -> str:
    """Keep filenames portable while preserving a useful extension."""
    raw_name = PurePosixPath((filename or "attachment").replace("\\", "/")).name
    cleaned = _SAFE_FILENAME_RE.sub("_", raw_name).strip("._")
    return (cleaned or "attachment")[:180]


def classify_attachment(content_type: str | None, filename: str | None) -> str:
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


def attachment_object_key(
    *,
    room_storage_key: uuid.UUID,
    attachment_id: uuid.UUID,
    data_type: str,
    filename: str,
) -> str:
    """S3 key for the binary payload."""
    return f"chats/{room_storage_key}/{data_type}/{attachment_id}_{filename}"


def metadata_object_key(*, room_storage_key: uuid.UUID, attachment_id: uuid.UUID) -> str:
    """S3 key for the JSON metadata snapshot."""
    return f"chats/{room_storage_key}/metadata/{attachment_id}.json"


async def read_upload_to_buffer(file: UploadFile) -> bytes:
    """Read an UploadFile fully into memory in 1 MiB chunks."""
    buffer = bytearray()
    while chunk := await file.read(1024 * 1024):
        buffer.extend(chunk)
    return bytes(buffer)


async def stream_upload_to_s3(
    file: UploadFile,
    *,
    storage: Storage,
    object_key: str,
    content_type: str,
) -> int:
    """Read the upload in 1 MiB chunks and PUT it to S3 in one shot.

    For chat attachments the payload is bounded by client UI limits, so a
    single ``put_object`` is fine; multipart upload would be premature here.
    """
    buffer = await read_upload_to_buffer(file)
    await storage.save(object_key, buffer, content_type=content_type)
    return len(buffer)


async def write_attachment_metadata(
    *,
    storage: Storage,
    room_storage_key: uuid.UUID,
    attachment: Any,
) -> None:
    """Persist a JSON snapshot next to the binary so off-DB tooling
    (object-browser, weekly archive) can resolve attachments without joining
    Postgres."""

    def dt(value: Any) -> str | None:
        return value.isoformat() if value is not None else None

    payload = {
        "id": str(attachment.id),
        "room_id": attachment.room_id,
        "message_id": str(attachment.message_id) if attachment.message_id else None,
        "filename": attachment.filename,
        "size": attachment.size,
        "content_type": attachment.content_type,
        "data_type": attachment.data_type,
        "storage_path": attachment.storage_path,
        "uploaded_by": attachment.uploaded_by,
        "created_at": dt(getattr(attachment, "created_at", None)),
        "updated_at": dt(getattr(attachment, "updated_at", None)),
    }
    body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    await storage.save(
        metadata_object_key(
            room_storage_key=room_storage_key, attachment_id=attachment.id
        ),
        body,
        content_type="application/json",
    )


__all__ = [
    "sanitize_filename",
    "classify_attachment",
    "attachment_object_key",
    "metadata_object_key",
    "read_upload_to_buffer",
    "stream_upload_to_s3",
    "write_attachment_metadata",
    "get_storage",
]
