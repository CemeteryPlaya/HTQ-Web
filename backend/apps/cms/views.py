"""HTTP views — ``/api/cms/v1/contact-requests/*``.

Ported from ``services/cms/app/api/v1/contact_requests.py``. Views stay
thin: parsing, auth, and status codes only — domain logic lives in
``apps.cms.services.contact_requests_service``.

Two URLs are shared by more than one HTTP method with *different* auth
requirements (``POST /`` is public, ``GET /`` is admin-only; the ``{id}``
detail URL is GET/PATCH/DELETE, all admin-only) — ``htqweb.http.api_view``
binds one auth mode per decorated function, so each shared URL gets a small
plain dispatcher that picks the right decorated function by
``request.method`` and falls back to a 405 envelope, matching the 405 a
router would give for an unregistered method on a real path.
"""

from __future__ import annotations

from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt

from htqweb.http import api_view, json_error

from . import schemas
from .services import contact_requests_service as svc


def _require_admin(request) -> None:
    if not request.token.is_elevated:
        raise PermissionDenied("Admin privileges required")


def _parse_bool(raw: str | None) -> bool | None:
    if raw is None:
        return None
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _parse_int(raw: str | None, default: int) -> int:
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


# ── POST / (public) + GET / (admin) — collection ────────────────────────────

@api_view(methods=("POST",), auth=None, body=schemas.ContactRequestCreate, status=201)
def _create_contact_request(request, data: schemas.ContactRequestCreate):
    entry = svc.create_contact_request(
        first_name=data.first_name,
        last_name=data.last_name,
        email=data.email,
        message=data.message,
    )
    return schemas.ContactRequestRead.model_validate(entry)


@api_view(methods=("GET",), auth="jwt")
def _list_contact_requests(request):
    _require_admin(request)
    handled = _parse_bool(request.GET.get("handled"))
    limit = max(1, min(_parse_int(request.GET.get("limit"), 50), 500))
    offset = max(0, _parse_int(request.GET.get("offset"), 0))
    rows = svc.list_contact_requests(handled=handled, limit=limit, offset=offset)
    return [schemas.ContactRequestRead.model_validate(row).model_dump(mode="json") for row in rows]


@csrf_exempt
def contact_requests_collection(request, *args, **kwargs):
    if request.method == "POST":
        return _create_contact_request(request, *args, **kwargs)
    if request.method == "GET":
        return _list_contact_requests(request, *args, **kwargs)
    return json_error("Method Not Allowed", 405)


# ── GET /stats (+ /stats/ alias), admin ─────────────────────────────────────

@api_view(methods=("GET",), auth="jwt")
def contact_request_stats(request):
    _require_admin(request)
    unhandled = svc.contact_request_stats()
    return schemas.ContactRequestStats(unhandled=unhandled)


# ── GET/PATCH/DELETE /{id}, admin — detail ──────────────────────────────────

@api_view(methods=("GET",), auth="jwt")
def _get_contact_request(request, contact_id: int):
    _require_admin(request)
    entry = svc.get_contact_request_or_404(contact_id)
    return schemas.ContactRequestRead.model_validate(entry)


@api_view(methods=("PATCH",), auth="jwt", body=schemas.ContactRequestUpdate)
def _update_contact_request(request, contact_id: int, data: schemas.ContactRequestUpdate):
    _require_admin(request)
    entry = svc.get_contact_request_or_404(contact_id)
    changes = data.model_dump(exclude_unset=True)
    entry = svc.update_contact_request(entry, changes)
    return schemas.ContactRequestRead.model_validate(entry)


@api_view(methods=("DELETE",), auth="jwt")
def _delete_contact_request(request, contact_id: int):
    _require_admin(request)
    entry = svc.get_contact_request_or_404(contact_id)
    svc.delete_contact_request(entry)
    return HttpResponse(status=204)


@csrf_exempt
def contact_request_detail(request, contact_id: int, *args, **kwargs):
    if request.method == "GET":
        return _get_contact_request(request, contact_id, *args, **kwargs)
    if request.method == "PATCH":
        return _update_contact_request(request, contact_id, *args, **kwargs)
    if request.method == "DELETE":
        return _delete_contact_request(request, contact_id, *args, **kwargs)
    return json_error("Method Not Allowed", 405)


# ── POST /{id}/reply, admin ─────────────────────────────────────────────────

@api_view(methods=("POST",), auth="jwt", body=schemas.ContactRequestReply)
def reply_contact_request(request, contact_id: int, data: schemas.ContactRequestReply):
    _require_admin(request)
    entry = svc.get_contact_request_or_404(contact_id)
    entry = svc.reply_to_contact_request(
        entry, reply_message=data.reply_message, admin_user_id=request.token.user_id,
    )
    return schemas.ContactRequestRead.model_validate(entry)
