"""Upload pipeline: validate → normalise → persist → enqueue variants.

This module is the single source of truth for accepting a new media file.
The HTTP router is a thin shim that parses the request and calls
``upload_file_bytes`` — that way the same pipeline is reusable from
worker / migration / CLI contexts (e.g., backfill).
"""

from __future__ import annotations

import datetime
import hashlib
import mimetypes
import uuid
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.scope_policy import ScopePolicy, get_policy, resolve_is_public
from app.core.settings import settings
from app.models.file_metadata import FileMetadata
from app.services.image_service import (
    ImageProcessingError,
    detect_mime,
    kind_from_mime,
    normalise as normalise_image,
)
from app.storage import Storage, get_storage


log = get_logger(__name__)


class UploadValidationError(ValueError):
    """Pipeline rejected the upload — caller maps to an HTTP status code."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass
class UploadResult:
    meta: FileMetadata
    enqueue_variants: bool
    deduplicated: bool


def _ext_for(mime: str, original_filename: str) -> str:
    # Prefer the explicit extension that matches the *true* mime; fall back to
    # the one carried in the filename so common odd names (e.g., ``.jpg``)
    # survive even when mimetypes guesses ``.jpe``.
    by_mime = mimetypes.guess_extension(mime) or ""
    if by_mime:
        # Normalise common alternates.
        if by_mime == ".jpe":
            return ".jpg"
        if by_mime == ".jpeg":
            return ".jpg"
        return by_mime
    if "." in original_filename:
        return "." + original_filename.rsplit(".", 1)[-1].lower()
    return ""


def _build_path(scope: str, file_id: uuid.UUID, ext: str) -> str:
    """Layout: ``<scope>/<yyyy>/<mm>/<uuid>/original<ext>``.

    Grouping by scope makes per-domain quotas / cleanup straightforward;
    nesting under <uuid>/ leaves room for sibling variants under the same
    prefix without colliding with other uploads.
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    return f"{scope}/{now.year}/{now.month:02d}/{file_id}/original{ext}"


def _validate_size(data: bytes, policy: ScopePolicy) -> None:
    size_mb = len(data) / (1024 * 1024)
    cap_mb = policy.max_mb if policy.max_mb is not None else settings.max_upload_size_mb
    if size_mb > cap_mb:
        raise UploadValidationError(
            413,
            f"File exceeds maximum allowed size of {cap_mb} MB",
        )


def _validate_mime(declared: str | None, real: str, policy: ScopePolicy) -> None:
    """Reject obvious polyglots: declared content-type must match the real mime
    (image/* family is forgiving to allow image/jpg vs image/jpeg etc.)."""
    if declared and declared != real:
        # Allow declared==image/* if real is also image/* — this normalises
        # synonyms (e.g., browser sends ``image/jpg``, magic returns
        # ``image/jpeg``). For non-image categories require strict equality.
        if not (declared.startswith("image/") and real.startswith("image/")):
            raise UploadValidationError(
                415,
                f"Declared Content-Type '{declared}' does not match detected '{real}'",
            )

    if policy.mimes and real not in policy.mimes:
        raise UploadValidationError(
            415,
            f"Mime '{real}' not allowed for scope '{policy.name}'. "
            f"Allowed: {list(policy.mimes)}",
        )

    if not policy.mimes and settings.allowed_mime_types:
        allowed = [m.strip() for m in settings.allowed_mime_types.split(",") if m.strip()]
        if allowed and real not in allowed:
            raise UploadValidationError(
                415,
                f"Mime '{real}' not in global allow-list",
            )


async def _find_duplicate(
    session: AsyncSession,
    *,
    sha256_hex: str,
    scope: str,
    owner_id: Optional[int],
) -> Optional[FileMetadata]:
    if not settings.dedup_enabled:
        return None
    stmt = (
        select(FileMetadata)
        .where(
            FileMetadata.sha256 == sha256_hex,
            FileMetadata.scope == scope,
            FileMetadata.owner_id == owner_id,
            FileMetadata.deleted_at.is_(None),
        )
        .limit(1)
    )
    res = await session.execute(stmt)
    return res.scalar_one_or_none()


async def upload_file_bytes(
    session: AsyncSession,
    *,
    data: bytes,
    declared_mime: str | None,
    original_filename: str,
    scope: str,
    requested_is_public: bool | None,
    owner_id: Optional[int],
    storage: Storage | None = None,
) -> UploadResult:
    """Accept raw bytes, run the pipeline, and persist a ``FileMetadata`` row.

    The caller (HTTP route or worker) is responsible for ``session.commit()``
    so the audit-log entry written alongside lives or dies with the upload.
    """
    policy = get_policy(scope)
    _validate_size(data, policy)

    real_mime = detect_mime(data, fallback=declared_mime)
    _validate_mime(declared_mime, real_mime, policy)
    kind = kind_from_mime(real_mime)

    # Hash the *original* (pre-normalisation) bytes so dedup works across
    # browsers that may inject slightly different metadata.
    sha256_hex = hashlib.sha256(data).hexdigest()

    final_is_public = resolve_is_public(scope, requested_is_public)

    duplicate = await _find_duplicate(
        session, sha256_hex=sha256_hex, scope=scope, owner_id=owner_id
    )
    if duplicate is not None and duplicate.deleted_at is None:
        log.info(
            "upload_deduplicated",
            existing_file_id=str(duplicate.id),
            sha256=sha256_hex,
            scope=scope,
            owner_id=owner_id,
        )
        return UploadResult(meta=duplicate, enqueue_variants=False, deduplicated=True)

    width: int | None = None
    height: int | None = None
    final_bytes = data
    final_mime = real_mime

    if kind == "image" and settings.strip_exif:
        try:
            normalised = normalise_image(data, real_mime)
            final_bytes = normalised.data
            final_mime = normalised.mime
            width = normalised.width
            height = normalised.height
        except ImageProcessingError as exc:
            raise UploadValidationError(415, f"invalid image: {exc}") from exc

    storage = storage or get_storage()
    file_uuid = uuid.uuid4()
    ext = _ext_for(final_mime, original_filename)
    path = _build_path(scope, file_uuid, ext)
    await storage.save(path, final_bytes)

    meta = FileMetadata(
        id=file_uuid,
        path=path,
        original_filename=original_filename or "",
        owner_id=owner_id,
        size=len(final_bytes),
        mime=final_mime,
        storage_backend=settings.storage_backend,
        is_public=final_is_public,
        sha256=sha256_hex,
        kind=kind,
        scope=scope,
        width=width,
        height=height,
        # Initialise the relationship explicitly so subsequent attribute
        # access (in serialize_file) does NOT trigger a lazy SELECT — async
        # SQLAlchemy raises ``MissingGreenlet`` for implicit IO inside a
        # sync attribute getter. A freshly-added file has no variants by
        # definition, so an empty list is the right initial state.
        variants=[],
    )
    session.add(meta)
    await session.flush()

    enqueue = bool(kind == "image" and policy.variants)
    return UploadResult(meta=meta, enqueue_variants=enqueue, deduplicated=False)
