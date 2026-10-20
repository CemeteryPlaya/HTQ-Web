"""Ручки портала поставщика ``/api/tender/v1/supplier/<token>/…`` (T3.2; план
этапа 3, §1, §2 T3.2).

Анонимный контур: каждая ручка — ``api_view(..., auth=None)`` (сторож
``test_gate.py`` ищет литерал). Доступ — пара «токен ссылки + cookie
устройства»: ``access.require_device(request, token)`` первой строкой каждой
ручки, кроме промежуточной карточки и ``bind``. Небезопасные методы — ещё
``Origin`` компании и тело JSON (там же; ``multipart`` — только у загрузки
файла). Тело разбирается ПОСЛЕ этих проверок (``access.parse_body``), а не
``api_view(body=…)``: иначе чужое устройство узнавало бы ответ разбора
раньше отказа, а битые запросы проходили мимо лимитов. Ответы — белым списком
(``services/portal/serializers.py``).

Ручки предложения и файлов КП (T3.3/T3.4) добавляются в этот же файл — по
тому же контракту ``access``.
"""

from __future__ import annotations

from django.db import transaction
from django.http import HttpResponseRedirect, JsonResponse

from apps.files import interface as files
from htqweb import ratelimit
from htqweb.errors import DomainError
from htqweb.http import api_view, json_error

from . import schemas
from .services.portal import access, binding, offers, serializers
from .services.portal import files as portal_files


# ── вход ────────────────────────────────────────────────────────────────

@api_view(methods=("GET",), auth=None)
def portal_card(request, token):
    """Промежуточная карточка по ссылке: ничего не пишет, cookie не ставит."""
    invitation, tender = access.resolve(request, token)
    bound = access.active_binding(invitation, access.device_secret(request)) is not None
    return serializers.card(request, tender, bound=bound)


@api_view(methods=("POST",), auth=None)
def portal_bind(request, token):
    """Привязать это устройство к приглашению (cookie, событие ``bound``)."""
    access.check_write(request)
    invitation, tender = access.resolve(request, token)
    access.throttle_bind(token)
    _binding, secret = binding.bind(invitation, request)
    response = JsonResponse(serializers.card(request, tender, bound=True))
    if secret is not None:
        access.set_device_cookie(response, secret, access.cookie_expires(tender))
    return response


# ── тендер и файлы ТЗ ───────────────────────────────────────────────────

@api_view(methods=("GET",), auth=None)
def portal_tender(request, token):
    ctx = access.require_device(request, token)
    return serializers.tender_view(request, ctx)


@api_view(methods=("GET",), auth=None)
def portal_spec_file(request, token, doc_id):
    """302 на временную ссылку файла ТЗ — только документы заявки этого
    тендера; выдача журналируется подсистемой (``file_downloaded``, IP)."""
    ctx = access.require_device(request, token)
    owner_id = ctx.tender.request_id
    known = {row["id"] for row in serializers.spec_files(ctx.tender)}
    if str(doc_id) not in known:
        raise access.dead_file()
    try:
        with transaction.atomic():
            url = files.download_link(serializers.SPEC_OWNER, owner_id, doc_id, actor_id=None,
                                      ip=ctx.ip, user_agent=ctx.user_agent)
    except files.FilesError:
        raise access.dead_file() from None
    return HttpResponseRedirect(url)



# ── предложение (T3.3) ──────────────────────────────────────────────────

def _event(ctx):
    """События портала — в журнал приглашения, в транзакции сервиса."""
    return lambda kind, meta: access.record_event(ctx, kind, meta)


@api_view(methods=("GET",), auth=None)
def portal_offer_get(request, token):
    ctx = access.require_device(request, token)
    return offers.offer_view(ctx)


@api_view(methods=("PUT",), auth=None)
def portal_offer_put(request, token):
    ctx = access.require_device(request, token)
    data = access.parse_body(request, schemas.PortalOfferIn)
    offers.save_draft(ctx, data.model_dump(exclude_unset=True), event=_event(ctx))
    return offers.offer_view(ctx)


def portal_offer(request, token):
    if request.method == "GET":
        return portal_offer_get(request, token)
    if request.method == "PUT":
        return portal_offer_put(request, token)
    return json_error("Method Not Allowed", 405)


@api_view(methods=("POST",), auth=None)
def portal_offer_submit(request, token):
    ctx = access.require_device(request, token)
    data = access.parse_body(request, schemas.PortalSubmitIn)
    offers.submit(ctx, data.model_dump(), event=_event(ctx))
    return offers.offer_view(ctx)


@api_view(methods=("POST",), auth=None)
def portal_offer_withdraw(request, token):
    ctx = access.require_device(request, token)
    data = access.parse_body(request, schemas.PortalVersionIn)
    offers.withdraw(ctx, data.model_dump(), event=_event(ctx))
    return offers.offer_view(ctx)


@api_view(methods=("POST",), auth=None)
def portal_decline(request, token):
    ctx = access.require_device(request, token)
    data = access.parse_body(request, schemas.PortalDeclineIn)
    offers.decline(ctx, data.model_dump(), event=_event(ctx))
    return offers.offer_view(ctx)


# ── файлы КП (T3.4) ─────────────────────────────────────────────────────

@api_view(methods=("GET",), auth=None)
def portal_offer_files_get(request, token):
    ctx = access.require_device(request, token)
    return portal_files.list_files(ctx)


@api_view(methods=("POST",), auth=None, status=201)
def portal_offer_files_post(request, token):
    """Загрузка (multipart, поле ``file``): сканер выключен — 503, лимит —
    30 в час на приглашение (429 + ``Retry-After``)."""
    ctx = access.require_device(request, token, multipart=True)
    portal_files.scanner_required()
    bucket, key = "tender_portal_upload", str(ctx.invitation.pk)
    if not ratelimit.hit(bucket, key, limit=portal_files.UPLOADS_PER_HOUR,
                         window=access.HOUR):
        raise access.rate_limited(bucket, key, access.HOUR)
    upload = request.FILES.get("file")
    if upload is None:
        raise DomainError("E-VAL-01", "Приложите файл.",
                          fields=[{"field": "file", "message": "Нет файла"}])
    return portal_files.upload(ctx, data=upload.read(), filename=upload.name,
                               mime=upload.content_type or "", ip=ctx.ip,
                               user_agent=ctx.user_agent, event=_event(ctx))


def portal_offer_files(request, token):
    if request.method == "GET":
        return portal_offer_files_get(request, token)
    if request.method == "POST":
        return portal_offer_files_post(request, token)
    return json_error("Method Not Allowed", 405)


@api_view(methods=("DELETE",), auth=None)
def portal_offer_file_delete(request, token, doc_id):
    ctx = access.require_device(request, token)
    portal_files.remove(ctx, doc_id, ip=ctx.ip, user_agent=ctx.user_agent,
                        event=_event(ctx))
    return {"deleted": True}
