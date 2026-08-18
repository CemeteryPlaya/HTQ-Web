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

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from pydantic import ValidationError

from htqweb.http import _authenticate_jwt, api_view, json_error

from .models import ConferenceInvite
from . import schemas
from . import tasks
from .services import audit
from .services import conference_invite_service
from .services import conference_service
from .services import contact_requests_service as svc
from .services import news_service as news_svc
from .services import taxonomy_service as tax_svc
from .tasks import notify_admins_on_contact_request

logger = logging.getLogger(__name__)


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


@api_view(methods=("GET",), auth="jwt", admin=True)
def _list_contact_requests(request):
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

@api_view(methods=("GET",), auth="jwt", admin=True)
def contact_request_stats(request):
    unhandled = svc.contact_request_stats()
    return schemas.ContactRequestStats(unhandled=unhandled)


# ── GET/PATCH/DELETE /{id}, admin — detail ──────────────────────────────────

@api_view(methods=("GET",), auth="jwt", admin=True)
def _get_contact_request(request, contact_id: int):
    entry = svc.get_contact_request_or_404(contact_id)
    return schemas.ContactRequestRead.model_validate(entry)


@api_view(methods=("PATCH",), auth="jwt", body=schemas.ContactRequestUpdate, admin=True)
def _update_contact_request(request, contact_id: int, data: schemas.ContactRequestUpdate):
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


@api_view(methods=("DELETE",), auth="jwt", admin=True)
def _delete_contact_request(request, contact_id: int):
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

@api_view(methods=("POST",), auth="jwt", body=schemas.ContactRequestReply, admin=True)
def reply_contact_request(request, contact_id: int, data: schemas.ContactRequestReply):
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


@api_view(methods=("POST",), auth="jwt", body=schemas.NewsCreate, status=201, admin=True)
def _create_news(request, data: schemas.NewsCreate):
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


@api_view(methods=("PATCH",), auth="jwt", body=schemas.NewsUpdate, admin=True)
def _update_news(request, news_id: int, data: schemas.NewsUpdate):
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


@api_view(methods=("DELETE",), auth="jwt", admin=True)
def _delete_news(request, news_id: int):
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


@api_view(methods=("POST",), auth="jwt", body=schemas.NewsTranslateRequest,
          status=202, admin=True)
def translate_news(request, news_id: int, data: schemas.NewsTranslateRequest):
    """Порт ``services/cms/app/api/v1/news.py::translate_news`` — единственный
    роут news.py, не перенесённый в фазу cutover'а: сама фоновая работа
    приехала (``apps.cms.tasks.translate_news``, порт ``workers/actors.py``),
    а ставящий её в очередь HTTP-эндпойнт — нет, из-за чего кнопка перевода
    во ``frontend/src/pages/NewsDetail.tsx`` получала 404, а ported-таск
    оставался недостижим.

    Контракт источника воспроизведён как есть: ``require_admin`` ->
    ``admin=True``, 404 на несуществующую новость, 202 + ``{task_id, news_id,
    target, status}``. Ответ ОСОЗНАННО асинхронный (никакого
    ``translated_title``/``translated_content`` в теле) — ровно как у
    источника; фронт эту ветку уже умеет («Перевод поставлен в очередь»)."""
    news = news_svc.get_news_for_admin_or_404(news_id)
    result = tasks.translate_news.delay(news.id, data.target)
    logger.info(
        "translate_news enqueued: news_id=%d target=%s task_id=%s by=%s",
        news.id, data.target, result.id, request.token.user_id,
    )
    return schemas.NewsTranslateResponse(
        task_id=str(result.id), news_id=news.id, target=data.target,
    )


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


@api_view(methods=("POST",), auth="jwt", body=schemas.CategoryCreate, status=201, admin=True)
def _create_category(request, data: schemas.CategoryCreate):
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

@api_view(methods=("PATCH",), auth="jwt", body=schemas.CategoryUpdate, admin=True)
def _update_category(request, category_id: int, data: schemas.CategoryUpdate):
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


@api_view(methods=("DELETE",), auth="jwt", admin=True)
def _delete_category(request, category_id: int):
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


@api_view(methods=("POST",), auth="jwt", body=schemas.TagCreate, status=201, admin=True)
def _create_tag(request, data: schemas.TagCreate):
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

@api_view(methods=("PATCH",), auth="jwt", body=schemas.TagUpdate, admin=True)
def _update_tag(request, tag_id: int, data: schemas.TagUpdate):
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


@api_view(methods=("DELETE",), auth="jwt", admin=True)
def _delete_tag(request, tag_id: int):
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


# ── Приглашения в конференцию ──────────────────────────────────────────────
#
# Два публичных маршрута из трёх — и это осознанно: человек, которого позвали
# ссылкой, учётки не имеет, значит проверить его нечем, кроме самого токена
# приглашения. Гостевой JWT, который он получает, не открывает ничего, кроме
# входа в ОДНУ комнату (см. htqweb/authn/jwt.py::issue_guest_token).

def _origin(request) -> str:
    """Адрес платформы так, как её видит БРАУЗЕР, а не бэкенд.

    Порядок источников выстрадан: ``request.get_host()`` наивно возвращал
    ``backend-web:8000`` — имя контейнера, которое прокси Vite ставит в
    ``Host`` (``changeOrigin: true``). Ссылка с таким хостом не открывается
    ни у кого: DNS_PROBE_FINISHED_NXDOMAIN.

    1. ``PUBLIC_BASE_URL`` — если задан, он и есть правда о публичном
       адресе; в письмах и сообщениях нужен именно он.
    2. Заголовок ``Origin`` — его ставит сам браузер на fetch/XHR, подделать
       его со стороны страницы нельзя. Покрывает dev, туннель и любой стенд,
       где переменную не выставляли.
    3. ``get_host()`` — последнее средство: лучше кривой хост, чем пустая
       ссылка, и в проде за nginx он как раз верный.
    """
    configured = (settings.PUBLIC_BASE_URL or "").strip()
    if configured:
        return configured.rstrip("/")

    origin = (request.headers.get("Origin") or "").strip()
    if origin.startswith("http://") or origin.startswith("https://"):
        return origin.rstrip("/")

    return f"{request.scheme}://{request.get_host()}"

@api_view(methods=("POST",), body=schemas.ConferenceInviteCreate, status=201)
def _create_conference_invite(request, data: schemas.ConferenceInviteCreate):
    try:
        invite = conference_invite_service.create_invite(
            room_id=data.room_id, created_by_id=request.token.user_id,
            title=data.title, allow_guests=data.allow_guests,
            ttl_hours=data.ttl_hours, max_uses=data.max_uses,
        )
    except conference_invite_service.InviteInvalid as exc:
        return json_error(exc.detail, 422)
    return schemas.ConferenceInviteRead.model_validate(
        conference_invite_service.serialize(invite, base_url=_origin(request)))


@api_view(methods=("GET",))
def _list_conference_invites(request):
    room_id = request.GET.get("room_id", "")
    if not room_id:
        return json_error("room_id is required", 422)
    return [
        schemas.ConferenceInviteRead.model_validate(
            conference_invite_service.serialize(inv, base_url=_origin(request)))
        for inv in conference_invite_service.list_for_room(room_id)
    ]


def conference_invites(request):
    if request.method == "GET":
        return _list_conference_invites(request)
    if request.method == "POST":
        return _create_conference_invite(request)
    return json_error("Method not allowed", 405)


@api_view(methods=("DELETE",), status=204)
def conference_invite_revoke(request, invite_id: int):
    try:
        conference_invite_service.revoke(invite_id)
    except conference_invite_service.InviteInvalid as exc:
        return json_error(exc.detail, 404)
    return HttpResponse(status=204)


@api_view(methods=("GET",), auth=None)
def conference_invite_public(request, token: str):
    """Что за встреча и можно ли войти гостем. Без авторизации — по эту
    ссылку человек приходит именно потому, что учётки у него нет.

    Сотруднику, открывшему ту же ссылку, дополнительно отдаётся комната: ему
    представляться незачем, он войдёт под собой и сразу. Анонимный
    посетитель идентификатор встречи не получает — до ввода имени он не
    участник.
    """
    try:
        invite = conference_invite_service.resolve(token)
    except conference_invite_service.InviteInvalid as exc:
        return json_error(exc.detail, 404)
    payload = {
        "title": invite.title,
        "allow_guests": invite.allow_guests,
        "expires_at": invite.expires_at,
        "room_id": invite.room_id if _authenticate_jwt(request) else None,
    }
    return schemas.ConferenceInvitePublic.model_validate(payload)


@api_view(methods=("POST",), auth=None, body=schemas.ConferenceGuestRequest)
def conference_invite_guest_token(request, token: str,
                                  data: schemas.ConferenceGuestRequest):
    """Выдать гостю токен на комнату этого приглашения.

    Отдельным шагом от проверки ссылки: предпросмотр в мессенджере или
    антивирус в почте открывают URL сами, и если бы токен выдавался на
    просмотре, лимит входов выжигался бы без единого живого участника.
    """
    try:
        invite = conference_invite_service.resolve(token)
        payload = conference_invite_service.issue_guest_access(
            invite, display_name=data.display_name)
    except conference_invite_service.InviteInvalid as exc:
        status = 404 if exc.code in ("not_found",) else 403
        return json_error(exc.detail, status)
    # Конфиг конференции кладём сюда же: у гостя нет платформенного токена,
    # а /conference/config за ним и остаётся — открывать его наружу ради
    # адреса сигналинга значило бы расширить публичную поверхность впустую.
    payload["conference"] = conference_service.get_conference_config(request)
    return schemas.ConferenceGuestToken.model_validate(payload)


@api_view(methods=("POST",), body=schemas.ConferenceInviteSend)
def conference_invite_send(request, invite_id: int, data: schemas.ConferenceInviteSend):
    """Отправить ссылку почтой и/или уведомлением в мессенджер."""
    invite = ConferenceInvite.objects.filter(pk=invite_id).first()
    if invite is None:
        return json_error("Приглашение не найдено", 404)
    if not data.emails and not data.user_ids:
        return json_error("Некому отправлять: укажите адреса или сотрудников", 422)

    sender = request.token.username or ""
    report = conference_invite_service.send_invite(
        invite, emails=[str(value) for value in data.emails],
        user_ids=data.user_ids, sender_name=sender, base_url=_origin(request),
    )
    return schemas.ConferenceInviteSendResult.model_validate(report)
