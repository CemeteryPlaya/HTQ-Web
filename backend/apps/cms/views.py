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

import json
import logging

from django.core.exceptions import PermissionDenied
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from pydantic import ValidationError

from htqweb.http import api_view, json_error

from . import schemas
from .services import audit
from .services import conference_service
from .services import contact_requests_service as svc
from .tasks import notify_admins_on_contact_request

logger = logging.getLogger(__name__)


def _require_admin(request) -> None:
    if not request.token.is_elevated:
        raise PermissionDenied("Admin privileges required")


# ── POST / (public) + GET / (admin) — collection ────────────────────────────

@api_view(methods=("POST",), auth=None, body=schemas.ContactRequestCreate, status=201)
def _create_contact_request(request, data: schemas.ContactRequestCreate):
    entry = svc.create_contact_request(
        first_name=data.first_name,
        last_name=data.last_name,
        email=data.email,
        message=data.message,
    )
    audit.record_action(
        request,
        user_id=None,
        action="contact_request_submitted",
        resource_type="ContactRequest",
        resource_id=str(entry.id),
        changes={"email": entry.email},
    )
    # Fire-and-forget notification to admins via email-service — ported
    # call site from services/cms/app/api/v1/contact_requests.py
    # (notify_admins_on_contact_request.send(entry.id)); Task 1.4
    # deliberately deferred this side effect until the task itself landed
    # (Task 1.7, apps/cms/tasks.py).
    #
    # Must never propagate: in CELERY_TASK_ALWAYS_EAGER=True (the whole test
    # suite) Celery runs .delay(...) inline and re-raises the task's own
    # exception back here (CELERY_TASK_EAGER_PROPAGATES=True), and in
    # production a broker hiccup can raise synchronously out of enqueue().
    # The ContactRequest row + audit entry above are already committed, so a
    # notification/broker failure must not turn an already-saved submission
    # into a 500 for the submitter.
    try:
        notify_admins_on_contact_request.delay(entry.id)
    except Exception:
        logger.exception(
            "notify_admins_on_contact_request enqueue/run failed for id=%d",
            entry.id,
        )
    return schemas.ContactRequestRead.model_validate(entry)


@api_view(methods=("GET",), auth="jwt")
def _list_contact_requests(request):
    _require_admin(request)
    try:
        query = schemas.ContactRequestListQuery.model_validate(dict(request.GET.items()))
    except ValidationError as exc:
        return JsonResponse({"detail": json.loads(exc.json())}, status=422)
    rows = svc.list_contact_requests(handled=query.handled, limit=query.limit, offset=query.offset)
    return [schemas.ContactRequestRead.model_validate(row) for row in rows]


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
    audit.record_action(
        request,
        user_id=request.token.user_id,
        action="contact_request_updated",
        resource_type="ContactRequest",
        resource_id=str(entry.id),
        changes=changes,
    )
    return schemas.ContactRequestRead.model_validate(entry)


@api_view(methods=("DELETE",), auth="jwt")
def _delete_contact_request(request, contact_id: int):
    _require_admin(request)
    entry = svc.get_contact_request_or_404(contact_id)
    email = entry.email
    contact_id_str = str(entry.id)
    svc.delete_contact_request(entry)
    audit.record_action(
        request,
        user_id=request.token.user_id,
        action="contact_request_deleted",
        resource_type="ContactRequest",
        resource_id=contact_id_str,
        changes={"email": email},
    )
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
    audit.record_action(
        request,
        user_id=request.token.user_id,
        action="contact_request_replied",
        resource_type="ContactRequest",
        resource_id=str(entry.id),
        changes={"reply_message": data.reply_message},
    )
    return schemas.ContactRequestRead.model_validate(entry)


# ── GET /conference/config (+ /conference/config/ alias) ────────────────────

@api_view(methods=("GET",), auth="jwt")
def conference_config(request):
    return conference_service.get_conference_config(request)
