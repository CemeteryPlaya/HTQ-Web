"""``media_files`` API views.

Task 3.2 shipped the upload endpoint. Task 3.3 adds serving: download the
original (Range/206/416/400, ETag, Accept-Ranges), download a variant, mint
a signed URL, and list files (admin) — ported from
``services/media/app/api/v1/files.py``'s ``download_file`` /
``download_variant`` / ``issue_signed_url`` / ``list_files`` routes.

Update/delete (``PATCH``/``DELETE /{file_id}``) are NOT ported here — out of
scope per the task 3.3 brief, later tasks.

**Raw storage-key serving (not in the FastAPI source):** originally added
(task 3.3) because ``apps.users.services.profile_service.save_avatar``
(task 2.3, decision Р3) wrote avatars straight to storage without a
``FileMetadata`` row, persisting ``avatar_url = f"/api/media/v1/files/
{key}?{signed_query(key)}"`` where ``key`` was the raw storage path (e.g.
``avatars/42/<uuid>.jpg`` — contains ``/``, never a bare UUID).
``serve_raw_key`` below is what made that URL fetchable: it verifies
``sig``/``exp`` against the raw key directly (no FileMetadata, no
public/JWT path — signature is the only access control) and, per
STRUCTURE.md §7.1's documented private-file flow, redirects (302) to a
fresh presigned S3 URL when ``STORAGE_BACKEND == "s3"`` or streams the
bytes directly for local dev (``LocalStorage.presigned_get_url`` returns a
non-fetchable ``file://`` URI, so redirecting there would break the
browser). The FastAPI ``files.py`` original/variant routes never redirect —
they always stream via ``storage.open()`` regardless of backend, reproduced
faithfully in ``download_file``/``download_variant`` below.

**Final review of phases 2-3 (Finding 2)** routed ``save_avatar`` through
the real upload pipeline (``apps.media_files.interface.store_file``)
instead of writing straight to storage — avatars are ``FileMetadata`` rows
now, served by ``download_file``/``download_variant`` above like any other
upload, not by ``serve_raw_key``. ``serve_raw_key`` is kept as
general-purpose raw-key serving infrastructure (still exercised directly by
its own tests) and as the read path for any pre-fix avatar rows still
carrying the old raw-key-shaped URL, but it is no longer written by
anything in this codebase.
"""

from __future__ import annotations

import logging
import mimetypes

from django.conf import settings
from django.http import HttpResponse, HttpResponseRedirect
from django.views.decorators.csrf import csrf_exempt

from htqweb.http import _authenticate_jwt, api_view, json_error
from htqweb.storage import get_storage, verify

from apps.media_files.models import FileMetadata, FileVariant
from apps.media_files.schemas import serialize_file
from apps.media_files.services import audit
from apps.media_files.services.upload_service import UploadValidationError, upload_file_bytes
from apps.media_files.services.url_service import build_file_url

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


# ─── Collection dispatch (GET list / POST upload on the same URL) ──────────
#
# ``htqweb.http.api_view`` dispatches on the URL alone, not method+URL like
# FastAPI — same reasoning as ``apps/cms/views.py``'s ``news_collection``,
# reused here rather than duplicated.


@csrf_exempt
def files_collection(request, *args, **kwargs):
    if request.method == "POST":
        return upload_file(request, *args, **kwargs)
    if request.method == "GET":
        return list_files(request, *args, **kwargs)
    return json_error("Method Not Allowed", 405)


@api_view(methods=("GET",), auth="jwt", admin=True)
def list_files(request):
    """``GET /api/media/v1/files/`` (admin only).

    Ported from the source's ``list_files`` — ``limit``/``offset`` query
    params, same bounds (``1<=limit<=500``, ``offset>=0``), soft-deleted
    rows excluded, newest first.
    """
    try:
        limit = int(request.GET.get("limit", 50))
        offset = int(request.GET.get("offset", 0))
    except ValueError:
        return json_error("'limit'/'offset' must be integers", 422)
    if not (1 <= limit <= 500) or offset < 0:
        return json_error("'limit' must be 1..500 and 'offset' must be >= 0", 422)

    rows = (
        FileMetadata.objects.filter(deleted_at__isnull=True)
        .order_by("-created_at")[offset : offset + limit]
    )
    return [serialize_file(r) for r in rows]


# ─── Access control (shared by download/variant/sign) ──────────────────────


def _can_access_private(user, meta: FileMetadata) -> bool:
    """Port of the source's ``_can_access_private`` minus the S2S
    (``user.is_service``) branch — this Django port carries no service-JWT
    concept (decision Р3, same omission as ``upload_service``'s dropped
    ``X-User-Id`` path).

    Uses ``is_elevated`` (the one platform admin predicate, see R1 — also
    what ``api_view(admin=True)``/``htqweb.authn.rbac.require_admin`` check)
    rather than the raw ``is_admin`` claim, so media's private-file access
    and its admin gate agree on the same flag."""
    if user is None:
        return False
    if user.is_elevated:
        return True
    return user.user_id == meta.owner_id


def _sig_valid(resource_id: str, sig_value: str | None, exp_value: str | None) -> bool:
    if not sig_value or not exp_value:
        return False
    try:
        return verify(resource_id, sig_value, int(exp_value))
    except (TypeError, ValueError):
        return False


def _quote_filename(name: str) -> str:
    """Strip CRLF and double-quotes from a filename used in a quoted-string
    Content-Disposition header (RFC 6266) to block header-injection — ported
    verbatim from the source's helper of the same name."""
    return name.replace('"', "").replace("\r", "").replace("\n", "")


# ─── Download (original) ────────────────────────────────────────────────────


@api_view(methods=("GET",), auth=None)
def download_file(request, file_id):
    """``GET /api/media/v1/files/{file_id}`` — download the original.

    Ported from the source's ``download_file``: HTTP Range support (206,
    416 on an unsatisfiable range, 400 on a malformed ``Range`` header —
    the source really does use 400 there, not 416), ``ETag``,
    ``Accept-Ranges``. Public files need no auth at all (``<img src>``
    can't send an ``Authorization`` header); private files need either a
    valid JWT (owner/admin) or a valid ``?sig=&exp=`` query pair.

    ``auth=None`` + manual ``_authenticate_jwt`` reproduces FastAPI's
    ``get_optional_user`` — same pattern as ``apps/cms/views.py``'s
    ``_list_news``/``_get_news`` (``htqweb.http.api_view`` only has
    "required jwt" or "no auth", no built-in optional mode).
    """
    user = _authenticate_jwt(request)
    meta = FileMetadata.objects.filter(pk=file_id).first()
    if meta is None or meta.deleted_at is not None:
        return json_error("File not found", 404)

    if not meta.is_public:
        sig_value = request.GET.get("sig")
        exp_value = request.GET.get("exp")
        if _sig_valid(str(meta.id), sig_value, exp_value):
            pass  # signed URL grants access
        elif _can_access_private(user, meta):
            pass
        elif user is None:
            return json_error("Not authenticated", 401)
        else:
            return json_error("Forbidden", 403)

    storage = get_storage(bucket=settings.MEDIA_S3_BUCKET)
    if not storage.exists(meta.path):
        return json_error("File physically missing", 404)

    total = meta.size
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Type": meta.mime,
        "Content-Disposition": f'inline; filename="{_quote_filename(meta.original_filename)}"',
        "ETag": f'"{meta.id}-{meta.updated_at.timestamp()}"',
    }

    range_header = request.headers.get("Range")
    if range_header:
        try:
            r = range_header.replace("bytes=", "").split("-", 1)
            start = int(r[0]) if r[0] else 0
            end = int(r[1]) if len(r) > 1 and r[1] else total - 1
            if start >= total or end >= total or start > end:
                headers["Content-Range"] = f"bytes */{total}"
                return HttpResponse(status=416, headers=headers)
        except ValueError:
            return json_error("Invalid Range Header", 400)
        headers["Content-Range"] = f"bytes {start}-{end}/{total}"
        headers["Content-Length"] = str(end - start + 1)
        data = storage.open(meta.path, byte_range=(start, end))
        return HttpResponse(data, status=206, headers=headers)

    headers["Content-Length"] = str(total)
    data = storage.open(meta.path)
    return HttpResponse(data, headers=headers)


# ─── Variant download ───────────────────────────────────────────────────────


@api_view(methods=("GET",), auth=None)
def download_variant(request, file_id, variant):
    """``GET /api/media/v1/files/{file_id}/{variant}`` — serve a derived
    variant (thumb_32 / thumb_96 / preview_1024 / ...).

    404 if the variant hasn't been produced yet — same contract as the
    source, frontend falls back to the original URL. Its ``ETag`` is a
    different, simpler shape than the original's (``"{variant_id}"`` vs
    ``"{file_id}-{timestamp}"``) — deliberate, matches the source, not
    unified.
    """
    user = _authenticate_jwt(request)
    meta = FileMetadata.objects.filter(pk=file_id).first()
    if meta is None or meta.deleted_at is not None:
        return json_error("File not found", 404)

    if not meta.is_public:
        sig_value = request.GET.get("sig")
        exp_value = request.GET.get("exp")
        # Resource id is scoped to `{file_id}:{variant}` (not the bare file
        # id) so a signed URL minted for one variant/original doesn't also
        # verify for a different one. The source achieves the same isolation
        # via a dedicated `variant` argument on its own sign()/verify(); this
        # port's shared `htqweb.storage.signed_url` (byte-for-byte parity
        # with the FastAPI cms stack, see its module docstring) only takes a
        # bare `resource_id`, so the variant is folded into that string
        # instead — same isolation property, different plumbing.
        if _sig_valid(f"{meta.id}:{variant}", sig_value, exp_value):
            pass
        elif _can_access_private(user, meta):
            pass
        elif user is None:
            return json_error("Not authenticated", 401)
        else:
            return json_error("Forbidden", 403)

    fv = FileVariant.objects.filter(file_id=file_id, variant=variant).first()
    if fv is None:
        return json_error(f"Variant '{variant}' not available", 404)

    storage = get_storage(bucket=settings.MEDIA_S3_BUCKET)
    if not storage.exists(fv.path):
        return json_error("Variant physically missing", 404)

    headers = {
        "Content-Type": fv.mime,
        "Content-Length": str(fv.size),
        "ETag": f'"{fv.id}"',
        "Cache-Control": (
            "public, max-age=31536000, immutable" if meta.is_public else "private, max-age=300"
        ),
    }
    data = storage.open(fv.path)
    return HttpResponse(data, headers=headers)


# ─── Signed URL ─────────────────────────────────────────────────────────────


@api_view(methods=("POST",), auth="jwt")
def issue_signed_url(request, file_id):
    """``POST /api/media/v1/files/{file_id}/sign?variant=original&ttl=3600``.

    Mints a short-lived HMAC-signed URL so the browser can fetch a private
    file via ``<img src>`` without an ``Authorization`` header. Only the
    owner/admin may sign on behalf of a file. Public files don't need
    signing — returns a plain URL anyway (uniform contract for callers).
    """
    meta = FileMetadata.objects.filter(pk=file_id).first()
    if meta is None or meta.deleted_at is not None:
        return json_error("File not found", 404)

    variant = request.GET.get("variant", "original")
    try:
        ttl = int(request.GET.get("ttl", 3600))
    except ValueError:
        return json_error("'ttl' must be an integer", 422)
    if not (60 <= ttl <= 24 * 3600):
        return json_error("'ttl' must be between 60 and 86400", 422)

    if not _can_access_private(request.token, meta) and not meta.is_public:
        return json_error("Forbidden", 403)

    url, exp = build_file_url(meta, variant=variant, ttl=ttl)
    return {"url": url, "exp": exp}


# ─── {file_id}/{tail} dispatch (GET variant vs POST sign) ──────────────────
#
# The source registers these as two routes sharing the same path shape
# (`{file_id}/{variant}` GET, `{file_id}/sign` POST) disambiguated purely by
# HTTP method — Starlette tries the GET route first for any GET request
# (including `GET .../sign`, where "sign" is just treated as a variant name
# and 404s if no such variant exists) and only a POST can ever reach the
# sign route. Django's `path()` doesn't dispatch on method, so this
# dispatcher reproduces that exact method-first behaviour on one URL entry.


@csrf_exempt
def file_tail_dispatch(request, file_id, tail):
    if request.method == "GET":
        return download_variant(request, file_id, tail)
    if request.method == "POST" and tail == "sign":
        return issue_signed_url(request, file_id)
    return json_error("Method Not Allowed", 405)


# ─── Raw storage-key serving (see module docstring) ────────────────────────


@api_view(methods=("GET",), auth=None)
def serve_raw_key(request, file_key):
    """``GET /api/media/v1/files/<key>?sig=&exp=`` — serve a file that has
    no ``FileMetadata`` row at all. Originally added for avatars written by
    ``apps.users.services.profile_service.save_avatar``; that no longer
    writes this shape (final review of phases 2-3, Finding 2 — see the
    module docstring), so this endpoint now only matters for any
    still-outstanding pre-fix avatar rows and as general-purpose raw-key
    serving infrastructure.

    No FileMetadata means no ``is_public``/owner concept — a valid
    ``sig``/``exp`` pair (checked against the raw key, matching
    ``signed_query(key)`` at write time) is the ONLY access control. Missing
    ``sig``/``exp`` → 401 (nothing supplied); present but invalid (tampered
    or expired) → 403 — same 401-vs-403 split as the FileMetadata routes.

    S3 backend: 302 redirect to a fresh presigned URL (STRUCTURE.md §7.1's
    documented private-file flow). Local backend: streams the bytes
    directly — ``LocalStorage.presigned_get_url`` returns a ``file://`` URI
    the browser can't fetch, so redirecting there would break the flow.
    """
    sig_value = request.GET.get("sig")
    exp_value = request.GET.get("exp")
    if not sig_value or not exp_value:
        return json_error("Not authenticated", 401)
    if not _sig_valid(file_key, sig_value, exp_value):
        return json_error("Forbidden", 403)

    storage = get_storage(bucket=settings.MEDIA_S3_BUCKET)
    if not storage.exists(file_key):
        return json_error("File not found", 404)

    if settings.STORAGE_BACKEND == "s3":
        return HttpResponseRedirect(storage.presigned_get_url(file_key))

    content_type, _ = mimetypes.guess_type(file_key)
    data = storage.open(file_key)
    return HttpResponse(data, content_type=content_type or "application/octet-stream")
