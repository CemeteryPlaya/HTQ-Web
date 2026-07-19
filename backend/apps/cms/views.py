"""HTTP views — ``/api/cms/v1/{contact-requests,news,categories,tags}/*``.

Ported from ``services/cms/app/api/v1/{contact_requests,news,taxonomy}.py``.
Views stay thin: parsing, auth, and status codes only — domain logic lives
in ``apps.cms.services.{contact_requests_service,news_service,
taxonomy_service}``.

Several URLs are shared by more than one HTTP method with *different* auth
requirements (e.g. ``POST /news/`` is admin-only, ``GET /news/`` is public;
the ``{id}`` detail URLs are GET-public/PATCH-admin/DELETE-admin) —
``htqweb.http.api_view`` binds one auth mode per decorated function, so each
shared URL gets a small plain dispatcher that picks the right decorated
function by ``request.method`` and falls back to a 405 envelope, matching
the 405 a router would give for an unregistered method on a real path.
"""

from __future__ import annotations

import json
import logging

from django.core.exceptions import PermissionDenied
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from pydantic import ValidationError

from htqweb.http import _authenticate_jwt, api_view, json_error

from . import schemas
from .services import audit
from .services import conference_service
from .services import contact_requests_service as svc
from .services import news_service as news_svc
from .services import taxonomy_service as tax_svc
from .tasks import notify_admins_on_contact_request

logger = logging.getLogger(__name__)


def _require_admin(request) -> None:
    if not request.token.is_elevated:
        raise PermissionDenied("Admin privileges required")


def _json_safe(value):
    """Coerce a single value into something Django's plain-JSON
    ``JSONField`` encoder can store — used only for the audit-log
    ``changes`` payload of ``PATCH /news/{id}``, whose applied-changes dict
    can contain a ``NewsStatus`` member (from the legacy ``published`` ->
    ``status`` derivation) or a ``datetime`` (``scheduled_at``), neither of
    which ``json.dumps`` accepts natively."""
    if hasattr(value, "value") and hasattr(value, "name"):  # Enum / TextChoices member
        return value.value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


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


# ── News: GET / (public) + POST / (admin) — collection ──────────────────────
#
# The list/detail GET routes are public but visibility-aware (admins see
# drafts/archived/scheduled too) — this is FastAPI's ``get_optional_user``
# dependency, which ``htqweb.http.api_view`` has no equivalent for (only
# "required jwt" or "no auth at all"). ``_authenticate_jwt`` is the same
# bearer-parsing helper ``api_view(auth="jwt")`` itself uses; reused here
# (not duplicated) to decode a token *if present* without 401ing when it
# isn't — the views are registered with ``auth=None`` and do this by hand.

@api_view(methods=("GET",), auth=None)
def _list_news(request):
    user = _authenticate_jwt(request)
    try:
        query = schemas.NewsListQuery.model_validate(dict(request.GET.items()))
    except ValidationError as exc:
        return JsonResponse({"detail": json.loads(exc.json())}, status=422)
    page = news_svc.list_news(
        user=user,
        category=query.category,
        tag=query.tag,
        status_filter=query.status,
        q=query.q,
        page=query.page,
        page_size=query.page_size,
    )
    return schemas.Page[schemas.NewsRead].model_validate(page)


@api_view(methods=("POST",), auth="jwt", body=schemas.NewsCreate, status=201)
def _create_news(request, data: schemas.NewsCreate):
    _require_admin(request)
    values = data.model_dump(exclude={"tag_ids"})
    if values.get("author_id") is None:
        values["author_id"] = request.token.user_id
    try:
        news = news_svc.create_news(values, tag_ids=data.tag_ids)
    except news_svc.ConflictError as exc:
        return JsonResponse({"detail": exc.detail}, status=409)
    audit.record_action(
        request,
        user_id=request.token.user_id,
        action="news_created",
        resource_type="News",
        resource_id=str(news.id),
        changes=data.model_dump(mode="json"),
    )
    return schemas.NewsRead.model_validate(news_svc.serialize_news(news))


@csrf_exempt
def news_collection(request, *args, **kwargs):
    if request.method == "GET":
        return _list_news(request, *args, **kwargs)
    if request.method == "POST":
        return _create_news(request, *args, **kwargs)
    return json_error("Method Not Allowed", 405)


# ── News: GET /by-slug/{slug} (public) ───────────────────────────────────────

@api_view(methods=("GET",), auth=None)
def news_by_slug(request, slug: str):
    user = _authenticate_jwt(request)
    news = news_svc.get_news_by_slug_or_404(slug, user=user)
    return schemas.NewsRead.model_validate(news_svc.serialize_news(news))


# ── News: GET /{id} (public) + PATCH /{id} (admin) + DELETE /{id} (admin) ───

@api_view(methods=("GET",), auth=None)
def _get_news(request, news_id: int):
    user = _authenticate_jwt(request)
    news = news_svc.get_news_or_404(news_id, user=user)
    return schemas.NewsRead.model_validate(news_svc.serialize_news(news))


@api_view(methods=("PATCH",), auth="jwt", body=schemas.NewsUpdate)
def _update_news(request, news_id: int, data: schemas.NewsUpdate):
    _require_admin(request)
    news = news_svc.get_news_for_admin_or_404(news_id)
    raw_changes = data.model_dump(exclude_unset=True)
    try:
        news, applied_changes = news_svc.update_news(news, raw_changes)
    except news_svc.ConflictError as exc:
        return JsonResponse({"detail": exc.detail}, status=409)
    audit.record_action(
        request,
        user_id=request.token.user_id,
        action="news_updated",
        resource_type="News",
        resource_id=str(news.id),
        changes={k: _json_safe(v) for k, v in applied_changes.items()},
    )
    return schemas.NewsRead.model_validate(news_svc.serialize_news(news))


@api_view(methods=("DELETE",), auth="jwt")
def _delete_news(request, news_id: int):
    _require_admin(request)
    news = news_svc.get_news_for_admin_or_404(news_id)
    slug = news.slug
    news_svc.delete_news(news)
    audit.record_action(
        request,
        user_id=request.token.user_id,
        action="news_deleted",
        resource_type="News",
        resource_id=str(news_id),
        changes={"slug": slug},
    )
    return HttpResponse(status=204)


@csrf_exempt
def news_detail(request, news_id: int, *args, **kwargs):
    if request.method == "GET":
        return _get_news(request, news_id, *args, **kwargs)
    if request.method == "PATCH":
        return _update_news(request, news_id, *args, **kwargs)
    if request.method == "DELETE":
        return _delete_news(request, news_id, *args, **kwargs)
    return json_error("Method Not Allowed", 405)


# ── Categories: GET / (public) + POST / (admin) — collection ────────────────

@api_view(methods=("GET",), auth=None)
def _list_categories(request):
    rows = tax_svc.list_categories()
    return [schemas.CategoryRead.model_validate(row) for row in rows]


@api_view(methods=("POST",), auth="jwt", body=schemas.CategoryCreate, status=201)
def _create_category(request, data: schemas.CategoryCreate):
    _require_admin(request)
    try:
        cat = tax_svc.create_category(data.model_dump())
    except tax_svc.ConflictError as exc:
        return JsonResponse({"detail": exc.detail}, status=409)
    audit.record_action(
        request,
        user_id=request.token.user_id,
        action="category_created",
        resource_type="Category",
        resource_id=str(cat.id),
        changes=data.model_dump(mode="json"),
    )
    return schemas.CategoryRead.model_validate(cat)


@csrf_exempt
def categories_collection(request, *args, **kwargs):
    if request.method == "GET":
        return _list_categories(request, *args, **kwargs)
    if request.method == "POST":
        return _create_category(request, *args, **kwargs)
    return json_error("Method Not Allowed", 405)


# ── Categories: PATCH /{id} (admin) + DELETE /{id} (admin) — detail ─────────

@api_view(methods=("PATCH",), auth="jwt", body=schemas.CategoryUpdate)
def _update_category(request, category_id: int, data: schemas.CategoryUpdate):
    _require_admin(request)
    cat = tax_svc.get_category_or_404(category_id)
    changes = data.model_dump(exclude_unset=True)
    try:
        cat = tax_svc.update_category(cat, changes)
    except tax_svc.ConflictError as exc:
        return JsonResponse({"detail": exc.detail}, status=409)
    audit.record_action(
        request,
        user_id=request.token.user_id,
        action="category_updated",
        resource_type="Category",
        resource_id=str(cat.id),
        changes=changes,
    )
    return schemas.CategoryRead.model_validate(cat)


@api_view(methods=("DELETE",), auth="jwt")
def _delete_category(request, category_id: int):
    _require_admin(request)
    cat = tax_svc.get_category_or_404(category_id)
    slug = cat.slug
    tax_svc.delete_category(cat)
    audit.record_action(
        request,
        user_id=request.token.user_id,
        action="category_deleted",
        resource_type="Category",
        resource_id=str(category_id),
        changes={"slug": slug},
    )
    return HttpResponse(status=204)


@csrf_exempt
def category_detail(request, category_id: int, *args, **kwargs):
    if request.method == "PATCH":
        return _update_category(request, category_id, *args, **kwargs)
    if request.method == "DELETE":
        return _delete_category(request, category_id, *args, **kwargs)
    return json_error("Method Not Allowed", 405)


# ── Tags: GET / (public) + POST / (admin) — collection ──────────────────────

@api_view(methods=("GET",), auth=None)
def _list_tags(request):
    rows = tax_svc.list_tags()
    return [schemas.TagRead.model_validate(row) for row in rows]


@api_view(methods=("POST",), auth="jwt", body=schemas.TagCreate, status=201)
def _create_tag(request, data: schemas.TagCreate):
    _require_admin(request)
    try:
        tag = tax_svc.create_tag(data.model_dump())
    except tax_svc.ConflictError as exc:
        return JsonResponse({"detail": exc.detail}, status=409)
    audit.record_action(
        request,
        user_id=request.token.user_id,
        action="tag_created",
        resource_type="Tag",
        resource_id=str(tag.id),
        changes=data.model_dump(mode="json"),
    )
    return schemas.TagRead.model_validate(tag)


@csrf_exempt
def tags_collection(request, *args, **kwargs):
    if request.method == "GET":
        return _list_tags(request, *args, **kwargs)
    if request.method == "POST":
        return _create_tag(request, *args, **kwargs)
    return json_error("Method Not Allowed", 405)


# ── Tags: PATCH /{id} (admin) + DELETE /{id} (admin) — detail ───────────────

@api_view(methods=("PATCH",), auth="jwt", body=schemas.TagUpdate)
def _update_tag(request, tag_id: int, data: schemas.TagUpdate):
    _require_admin(request)
    tag = tax_svc.get_tag_or_404(tag_id)
    changes = data.model_dump(exclude_unset=True)
    try:
        tag = tax_svc.update_tag(tag, changes)
    except tax_svc.ConflictError as exc:
        return JsonResponse({"detail": exc.detail}, status=409)
    audit.record_action(
        request,
        user_id=request.token.user_id,
        action="tag_updated",
        resource_type="Tag",
        resource_id=str(tag.id),
        changes=changes,
    )
    return schemas.TagRead.model_validate(tag)


@api_view(methods=("DELETE",), auth="jwt")
def _delete_tag(request, tag_id: int):
    _require_admin(request)
    tag = tax_svc.get_tag_or_404(tag_id)
    slug = tag.slug
    tax_svc.delete_tag(tag)
    audit.record_action(
        request,
        user_id=request.token.user_id,
        action="tag_deleted",
        resource_type="Tag",
        resource_id=str(tag_id),
        changes={"slug": slug},
    )
    return HttpResponse(status=204)


@csrf_exempt
def tag_detail(request, tag_id: int, *args, **kwargs):
    if request.method == "PATCH":
        return _update_tag(request, tag_id, *args, **kwargs)
    if request.method == "DELETE":
        return _delete_tag(request, tag_id, *args, **kwargs)
    return json_error("Method Not Allowed", 405)
