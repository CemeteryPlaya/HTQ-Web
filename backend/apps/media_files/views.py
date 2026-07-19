"""``media_files`` API views — task 3.2 ships only the upload endpoint.

Ported from ``services/media/app/api/v1/files.py``'s ``upload_file`` route.
Download/list/update/delete/sign routes from the source are later tasks
(3.3+) — not built here.
"""

from __future__ import annotations

import logging

from htqweb.http import api_view, json_error

from apps.media_files.schemas import serialize_file
from apps.media_files.services import audit
from apps.media_files.services.upload_service import UploadValidationError, upload_file_bytes

logger = logging.getLogger(__name__)


def _parse_is_public(raw: str | None) -> bool | None:
    """Multipart form fields arrive as strings. ``None`` (field absent) is
    distinct from an explicit false — ``resolve_is_public`` needs that
    distinction (an absent field defers entirely to scope policy)."""
    if raw is None:
        return None
    return raw.strip().lower() in ("1", "true", "yes", "on")


@api_view(methods=("POST",), auth="jwt", status=201)
def upload_file(request):
    """``POST /api/media/v1/files/`` (multipart/form-data).

    Fields: ``file`` (required), ``scope`` (default ``"generic"``),
    ``is_public`` (optional bool string).

    The pipeline (declared/real mime, size/scope validation via
    ``ScopePolicy``, EXIF strip, sha256, storage write, ``FileMetadata``
    persistence) lives in ``apps.media_files.services.upload_service``; this
    view handles HTTP concerns only, same split as the FastAPI source's
    router vs. ``media_service``.
    """
    upload = request.FILES.get("file")
    if upload is None:
        return json_error("Field 'file' is required", 422)

    scope = request.POST.get("scope") or "generic"
    is_public = _parse_is_public(request.POST.get("is_public"))
    owner_id = request.token.user_id

    try:
        result = upload_file_bytes(
            data=upload.read(),
            declared_mime=upload.content_type,
            original_filename=upload.name or "",
            scope=scope,
            requested_is_public=is_public,
            owner_id=owner_id,
        )
    except UploadValidationError as exc:
        return json_error(exc.detail, exc.status_code)

    meta = result.meta

    audit.record_action(
        request,
        user_id=owner_id,
        action="file_uploaded",
        resource_type="FileMetadata",
        resource_id=str(meta.id),
        changes={
            "path": meta.path,
            "size": meta.size,
            "mime": meta.mime,
            "kind": meta.kind,
            "scope": meta.scope,
            "sha256": meta.sha256,
            "is_public": meta.is_public,
        },
    )

    logger.info(
        "file_uploaded file_id=%s size=%d owner_id=%s scope=%s kind=%s is_public=%s",
        meta.id, meta.size, owner_id, meta.scope, meta.kind, meta.is_public,
    )

    if result.enqueue_variants:
        # Fire-and-forget (same precedent as apps/cms/views.py's
        # notify_admins_on_contact_request.delay() call): the FileMetadata
        # row is already committed above, so a broker hiccup — or, in
        # CELERY_TASK_ALWAYS_EAGER=True, the task itself raising, which
        # CELERY_TASK_EAGER_PROPAGATES=True re-raises synchronously right
        # here — must not turn an already-saved upload into a 500.
        from apps.media_files.tasks import make_variants

        try:
            make_variants.delay(str(meta.id))
        except Exception:
            logger.exception("make_variants enqueue/run failed for id=%s", meta.id)

    return serialize_file(meta)
