"""Upload pipeline: validate → normalise → persist → decide variant enqueue.

Ported from ``services/media/app/services/media_service.py``'s
``upload_file_bytes`` (and its private helpers ``_ext_for``, ``_build_path``,
``_validate_size``, ``_validate_mime``). The Django port is synchronous
(idiomatic ORM, no asyncio) and skips two source features that don't apply
here:

- **No S2S owner resolution** (decision Р3, task brief) — the caller
  (``apps.media_files.views.upload_file``) always passes the JWT's own
  ``user_id`` as ``owner_id``; the source's ``X-User-Id`` header path for
  service-JWT callers has no port.
- **No sha256 dedup lookup** — the source's ``_find_duplicate`` is gated by
  ``settings.dedup_enabled`` which **defaults to ``False`` upstream too**
  (``services/media/app/core/settings.py``), so skipping it reproduces the
  source's default behaviour exactly; only a deployment that opted into
  dedup via env would see a difference, and this port has no equivalent
  toggle. sha256 is still computed and stored on every row (needed by
  ``FileMetadata.sha256`` and asserted by the task 3.2 tests) — only the
  "return the existing row instead of writing a new one" step is not
  ported.
"""

from __future__ import annotations

import datetime
import hashlib
import mimetypes
import uuid
from dataclasses import dataclass

from django.conf import settings

from htqweb.storage import get_storage

from apps.media_files.models import FileMetadata
from apps.media_files.services.image_service import (
    ImageProcessingError,
    detect_mime,
    kind_from_mime,
    normalise as normalise_image,
)
from apps.media_files.services.scope_policy import ScopePolicy, get_policy, resolve_is_public


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


def _ext_for(mime: str, original_filename: str) -> str:
    # Prefer the explicit extension that matches the *true* mime; fall back to
    # the one carried in the filename so common odd names (e.g., ``.jpg``)
    # survive even when mimetypes guesses ``.jpe``.
    by_mime = mimetypes.guess_extension(mime) or ""
    if by_mime:
        # Normalise common alternates.
        if by_mime in (".jpe", ".jpeg"):
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
    cap_mb = policy.max_mb if policy.max_mb is not None else settings.MAX_UPLOAD_SIZE_MB
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

    if not policy.mimes and settings.ALLOWED_MIME_TYPES:
        allowed = [m.strip() for m in settings.ALLOWED_MIME_TYPES.split(",") if m.strip()]
        if allowed and real not in allowed:
            raise UploadValidationError(
                415,
                f"Mime '{real}' not in global allow-list",
            )


def upload_file_bytes(
    *,
    data: bytes,
    declared_mime: str | None,
    original_filename: str,
    scope: str,
    requested_is_public: bool | None,
    owner_id: int | None,
) -> UploadResult:
    """Accept raw bytes, run the pipeline, and persist a ``FileMetadata`` row.

    Raises ``UploadValidationError`` (caller maps ``.status_code``/``.detail``
    to an HTTP response) for oversize/wrong-mime/undecodable-image inputs.
    """
    policy = get_policy(scope)
    _validate_size(data, policy)

    real_mime = detect_mime(data, fallback=declared_mime)
    _validate_mime(declared_mime, real_mime, policy)
    kind = kind_from_mime(real_mime)

    # Hash the *original* (pre-normalisation) bytes so a future dedup lookup
    # (see module docstring) would work across browsers that may inject
    # slightly different metadata.
    sha256_hex = hashlib.sha256(data).hexdigest()

    final_is_public = resolve_is_public(scope, requested_is_public)

    width: int | None = None
    height: int | None = None
    final_bytes = data
    final_mime = real_mime

    if kind == "image" and settings.STRIP_EXIF:
        try:
            normalised = normalise_image(data, real_mime)
            final_bytes = normalised.data
            final_mime = normalised.mime
            width = normalised.width
            height = normalised.height
        except ImageProcessingError as exc:
            raise UploadValidationError(415, f"invalid image: {exc}") from exc

    storage = get_storage(bucket=settings.MEDIA_S3_BUCKET)
    file_uuid = uuid.uuid4()
    ext = _ext_for(final_mime, original_filename)
    path = _build_path(scope, file_uuid, ext)
    storage.save(path, final_bytes, content_type=final_mime)

    meta = FileMetadata.objects.create(
        id=file_uuid,
        path=path,
        original_filename=original_filename or "",
        owner_id=owner_id,
        size=len(final_bytes),
        mime=final_mime,
        storage_backend=settings.STORAGE_BACKEND,
        is_public=final_is_public,
        sha256=sha256_hex,
        kind=kind,
        scope=scope,
        width=width,
        height=height,
    )

    enqueue = bool(kind == "image" and policy.variants)
    return UploadResult(meta=meta, enqueue_variants=enqueue)
