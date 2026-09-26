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
import re
import uuid
from dataclasses import dataclass

import logging

from django.conf import settings

from htqweb import antivirus
from htqweb.http import ApiError
from htqweb.storage import get_storage

from apps.media_files.models import FileMetadata
from apps.media_files.services.content_signature import SignatureCheck, verify_signature
from apps.media_files.services.image_service import (
    ImageProcessingError,
    detect_mime,
    kind_from_mime,
    normalise as normalise_image,
    validate as validate_image,
)
from apps.media_files.services.scope_policy import (
    ScopePolicy,
    get_policy,
    normalize_scope,
    resolve_is_public,
)


class UploadValidationError(ApiError, ValueError):
    """Pipeline rejected the upload — caller maps to an HTTP status code.

    ``ApiError`` — чтобы отказ, не перехваченный вызывающей аппкой, всё равно
    дошёл до клиента своим статусом и текстом, а не 500 (``api_view``);
    ``ValueError`` — прежний контракт для тех, кто ловит его сам.
    """

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class FileInfected(UploadValidationError):
    """Антивирус нашёл угрозу — файл не сохраняется.

    Текст — для человека и по-русски: его показывают и вьюхи, которые сами
    отказ не разбирают (договорный контур, согласование).
    """

    def __init__(self, signature: str) -> None:
        super().__init__(
            422, f"Файл не загружен: антивирус обнаружил угрозу «{signature}». "
                 f"Проверьте файл и компьютер антивирусом и загрузите чистую копию.")
        self.signature = signature


class ScanUnavailable(UploadValidationError):
    """Scope требует проверки, а сканер не ответил — файл не сохраняется."""

    def __init__(self, reason: str) -> None:
        super().__init__(
            503, "Файл не загружен: проверка на вирусы сейчас недоступна, а без "
                 "неё файлы не принимаются. Повторите загрузку через несколько минут.")
        self.reason = reason


logger = logging.getLogger(__name__)


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


def _build_path(scope: str, file_id: uuid.UUID, ext: str,
                folder: str | None = None) -> str:
    """Layout: ``<scope>/<yyyy>/<mm>/<uuid>/original<ext>``, or
    ``<scope>/<folder>/<uuid>/original<ext>`` for a ``folder_layout`` scope.

    Grouping by scope makes per-domain quotas / cleanup straightforward;
    nesting under <uuid>/ leaves room for sibling variants under the same
    prefix without colliding with other uploads. A folder replaces the date
    part: every file of one owner object (e.g. one request) then shares one
    prefix, which is what "one object = one folder" means in storage.
    """
    if folder is not None:
        return f"{scope}/{folder}/{file_id}/original{ext}"
    now = datetime.datetime.now(datetime.timezone.utc)
    return f"{scope}/{now.year}/{now.month:02d}/{file_id}/original{ext}"


# Сегменты папки — только то, что безопасно в ключе S3 и в пути ФС: у
# S3-бэкенда нет своей защиты от ``..`` (она есть только у LocalStorage).
_FOLDER_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}(?:/[a-z0-9][a-z0-9_-]{0,63}){0,3}")


def _resolve_folder(folder: str | None, policy: ScopePolicy) -> str | None:
    """Папка обязательна для ``folder_layout``-scope и запрещена для прочих.

    Строго в обе стороны: раскладка ключей — свойство scope, и смешение двух
    схем в одном префиксе сделало бы его нечитаемым. Заодно это закрывает
    прямую загрузку в такой scope через ``POST /api/media/v1/files/``: HTTP-
    эндпоинт папку не передаёт, и файл без владельца туда не ляжет.
    """
    if not policy.folder_layout:
        if folder is not None:
            raise UploadValidationError(
                422, f"Scope '{policy.name}' does not use folders")
        return None
    if folder is None:
        raise UploadValidationError(
            422, f"Scope '{policy.name}' requires a folder")
    if not _FOLDER_RE.fullmatch(folder):
        raise UploadValidationError(422, f"Invalid folder {folder!r}")
    return folder


def _validate_size(data: bytes, policy: ScopePolicy) -> None:
    size_mb = len(data) / (1024 * 1024)
    cap_mb = policy.max_mb if policy.max_mb is not None else settings.MAX_UPLOAD_SIZE_MB
    if size_mb > cap_mb:
        raise UploadValidationError(
            413,
            f"File exceeds maximum allowed size of {cap_mb} MB",
        )


def _validate_mime(real: str, policy: ScopePolicy) -> None:
    """Reject a real mime the scope (or the global allow-list) doesn't permit.

    NOTE: this used to also compare a "declared" mime against "real" and
    reject a mismatch, but that branch was dead code: ``real`` (from
    ``image_service.detect_mime``) is always exactly the declared
    Content-Type or the "application/octet-stream" fallback — there is no
    independent "real" mime to disagree with it, because python-magic isn't
    used here (see ``image_service.py``'s module docstring — it segfaults on
    this Windows host). The actual content-vs-declared check now lives in
    ``_validate_signature`` below (magic-byte signatures, no native deps),
    which fires for scopes that restrict mimes.
    """
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


def _validate_signature(data: bytes, mime: str, policy: ScopePolicy) -> None:
    """Verify magic-byte signature for restricted-mime scopes.

    This is the substitute for python-magic (see ``_validate_mime``'s
    docstring and ``image_service.py``'s module docstring for why it isn't
    used). Image scopes are already content-verified by Pillow's decode in
    ``normalise()``; this closes the gap for non-image restricted scopes
    (e.g. ``hr_doc`` → ``application/pdf``) that never go through Pillow, so
    a caller can't POST arbitrary bytes under a trusted Content-Type.

    Only fires when the policy restricts mimes — permissive scopes
    (``chat``/``generic``, ``policy.mimes == ()``) accept arbitrary mimes on
    purpose and must not be blocked here. Also does not fire (does not
    block) when the declared mime has no known signature — see
    ``content_signature.SignatureCheck.UNKNOWN``.
    """
    if not policy.mimes:
        return
    if verify_signature(data, mime) is SignatureCheck.MISMATCH:
        raise UploadValidationError(
            415,
            f"File content does not match declared Content-Type '{mime}'",
        )


def _scan(data: bytes, filename: str, policy: ScopePolicy) -> None:
    """Антивирус — после дешёвых проверок (размер, тип, сигнатура), но ДО
    разбора картинки и записи: байты, которые клиент прислал, а не то, во
    что их превратила обработка."""
    if not policy.antivirus or not antivirus.enabled():
        return
    try:
        verdict = antivirus.scan(data)
    except antivirus.ScanUnavailable as exc:
        logger.error("antivirus unavailable, upload of %r refused: %s", filename, exc)
        raise ScanUnavailable(str(exc)) from exc
    if not verdict.clean:
        logger.warning("antivirus: %r rejected, signature %s", filename, verdict.signature)
        raise FileInfected(verdict.signature)


def upload_file_bytes(
    *,
    data: bytes,
    declared_mime: str | None,
    original_filename: str,
    scope: str,
    requested_is_public: bool | None,
    owner_id: int | None,
    folder: str | None = None,
) -> UploadResult:
    """Accept raw bytes, run the pipeline, and persist a ``FileMetadata`` row.

    ``folder`` — папка владельца для ``folder_layout``-scope (см.
    ``_resolve_folder``); у остальных scope должна быть ``None``.

    Raises ``UploadValidationError`` (caller maps ``.status_code``/``.detail``
    to an HTTP response) for oversize/wrong-mime/undecodable-image inputs.
    """
    # Canonicalise the client-supplied scope once, up front, so the storage
    # path (_build_path), the policy lookup, and the persisted FileMetadata.scope
    # all use the same normalized form (see scope_policy.normalize_scope).
    scope = normalize_scope(scope)
    policy = get_policy(scope)
    folder = _resolve_folder(folder, policy)
    _validate_size(data, policy)

    real_mime = detect_mime(data, fallback=declared_mime)
    _validate_mime(real_mime, policy)
    _validate_signature(data, real_mime, policy)
    _scan(data, original_filename, policy)
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

    if kind == "image" and settings.STRIP_EXIF and not policy.keep_original:
        try:
            normalised = normalise_image(data, real_mime)
            final_bytes = normalised.data
            final_mime = normalised.mime
            width = normalised.width
            height = normalised.height
        except ImageProcessingError as exc:
            raise UploadValidationError(415, f"invalid image: {exc}") from exc
    elif kind == "image" and policy.keep_original:
        # Байты не трогаем (SHA-256 должен описывать хранимое), но
        # декодируемость и предел пикселей проверяем так же, как normalise.
        try:
            width, height = validate_image(data)
        except ImageProcessingError as exc:
            raise UploadValidationError(415, f"invalid image: {exc}") from exc

    storage = get_storage(bucket=settings.MEDIA_S3_BUCKET)
    file_uuid = uuid.uuid4()
    ext = _ext_for(final_mime, original_filename)
    path = _build_path(scope, file_uuid, ext, folder)
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


def read_original(meta: FileMetadata) -> bytes:
    """Байты оригинала из хранилища — тем же ``get_storage``, которым
    ``upload_file_bytes`` их туда положил (и который подменяют тесты)."""
    return get_storage(bucket=settings.MEDIA_S3_BUCKET).open(meta.path)
