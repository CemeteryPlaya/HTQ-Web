"""Ручки тендера и его участников (T2.1, T2.2; план этапов 0–2, §4.3).

Каждая — под гейтом модуля ``tender`` с явным уровнем (чтение — ``read``,
запись — ``write``); узел ``tender.tenders``, авторство и статус проверяет
сервис (``services/tenders/``). Ссылка поставщика (``link``) — только в
ответах публикации, перевыпуска и приглашения после публикации.
"""

from __future__ import annotations

from django.http import HttpResponseRedirect

from htqweb.errors import DomainError
from htqweb.http import api_view, json_error

from . import schemas
from .services.comparison import export as comparison_export
from .services.award import selection
from .services.award import submit as award_submit
from .services.comparison import opening, table
from .services.portal import access as portal_access
from .services.tenders import invitations, tenders
from .services.tenders.ctx import Ctx


def _int(params, name: str, default: int, *, maximum: int) -> int:
    raw = params.get(name)
    if raw in (None, ""):
        return default
    try:
        value = int(raw)
    except ValueError:
        raise DomainError("E-VAL-01", f"Параметр {name} — целое число.",
                          fields=[{"field": name, "message": "Целое число"}]) from None
    return max(1, min(value, maximum))


def _card(request, tender) -> dict:
    return tenders.card(Ctx.from_request(request), tender)


# ── реестр и черновик ───────────────────────────────────────────────────

@api_view(methods=("GET",), module="tender", level="read")
def tender_list(request):
    params = request.GET
    return tenders.registry(
        Ctx.from_request(request), statuses=[s for s in params.getlist("status") if s],
        request_id=params.get("request_id") or None, query=(params.get("q") or "").strip(),
        page=_int(params, "page", 1, maximum=10**6),
        page_size=_int(params, "page_size", 50, maximum=200))


@api_view(methods=("POST",), module="tender", level="write", body=schemas.TenderCreate,
          status=201, idempotent=True)
def tender_create(request, data):
    return _card(request, tenders.create(Ctx.from_request(request), data.model_dump()))


def tenders_collection(request):
    if request.method == "GET":
        return tender_list(request)
    if request.method == "POST":
        return tender_create(request)
    return json_error("Method Not Allowed", 405)


@api_view(methods=("GET",), module="tender", level="read")
def tender_get(request, tender_id):
    return _card(request, tenders.get_visible(Ctx.from_request(request), tender_id))


@api_view(methods=("PATCH",), module="tender", level="write", body=schemas.TenderUpdate,
          idempotent=True)
def tender_patch(request, tender_id, data):
    sent = data.model_dump(exclude_unset=True)
    version = sent.pop("version", None)
    return _card(request, tenders.update(Ctx.from_request(request), tender_id,
                                         expected_version=version, data=sent))


def tender_detail(request, tender_id):
    if request.method == "GET":
        return tender_get(request, tender_id)
    if request.method == "PATCH":
        return tender_patch(request, tender_id)
    return json_error("Method Not Allowed", 405)


@api_view(methods=("PUT",), module="tender", level="write", body=schemas.PaymentSchemeIn,
          idempotent=True)
def tender_payment_scheme(request, tender_id, data):
    return _card(request, tenders.set_payment_scheme(
        Ctx.from_request(request), tender_id, kind=data.kind, advance_pct=data.advance_pct,
        postpay_days=data.postpay_days))


# ── жизненный цикл ──────────────────────────────────────────────────────

@api_view(methods=("POST",), module="tender", level="write", body=schemas.TenderVersion,
          idempotent=True)
def tender_publish(request, tender_id, data):
    return {"links": tenders.publish(Ctx.from_request(request), tender_id,
                                     expected_version=data.version)}


@api_view(methods=("POST",), module="tender", level="write", body=schemas.TenderExtend,
          idempotent=True)
def tender_extend(request, tender_id, data):
    return _card(request, tenders.extend(Ctx.from_request(request), tender_id,
                                         expected_version=data.version,
                                         deadline_at=data.deadline_at))


@api_view(methods=("POST",), module="tender", level="write", body=schemas.TenderCancel,
          idempotent=True)
def tender_cancel(request, tender_id, data):
    return _card(request, tenders.cancel(Ctx.from_request(request), tender_id,
                                         expected_version=data.version, reason=data.reason))


@api_view(methods=("POST",), module="tender", level="write", body=schemas.TenderVersion,
          idempotent=True)
def tender_open(request, tender_id, data):
    return _card(request, opening.open_tender(Ctx.from_request(request), tender_id,
                                              expected_version=data.version))


@api_view(methods=("GET",), module="tender", level="read")
def tender_comparison(request, tender_id):
    return table.comparison(Ctx.from_request(request), tender_id)


@api_view(methods=("GET",), module="tender", level="read")
def tender_award_get(request, tender_id):
    return selection.view(Ctx.from_request(request), tender_id)


@api_view(methods=("PUT",), module="tender", level="write", body=schemas.AwardIn)
def tender_award_put(request, tender_id, data):
    return selection.save(Ctx.from_request(request), tender_id, data.model_dump())


@api_view(methods=("POST",), module="tender", level="write", body=schemas.TenderVersion,
          idempotent=True)
def tender_award_submit(request, tender_id, data):
    return award_submit.submit(Ctx.from_request(request), tender_id,
                               expected_version=data.version)


def tender_award(request, tender_id):
    if request.method == "GET":
        return tender_award_get(request, tender_id)
    if request.method == "PUT":
        return tender_award_put(request, tender_id)
    return json_error("Method Not Allowed", 405)


@api_view(methods=("GET",), module="tender", level="read")
def tender_comparison_export(request, tender_id):
    return comparison_export.export(Ctx.from_request(request), tender_id)


@api_view(methods=("GET",), module="tender", level="read")
def tender_offer_file(request, tender_id, offer_id, doc_id):
    """Файл КП вскрытого предложения — 302 на временную ссылку (журнал выдачи)."""
    return HttpResponseRedirect(table.offer_file_link(
        Ctx.from_request(request), tender_id, offer_id, doc_id,
        ip=portal_access.client_ip(request), user_agent=portal_access.user_agent(request)))


# ── участники ───────────────────────────────────────────────────────────

@api_view(methods=("GET",), module="tender", level="read")
def invitation_list(request, tender_id):
    return invitations.list_for(Ctx.from_request(request), tender_id)


@api_view(methods=("POST",), module="tender", level="write", body=schemas.InvitationIn,
          status=201, idempotent=True)
def invitation_create(request, tender_id, data):
    return invitations.add(Ctx.from_request(request), tender_id, data.model_dump())


def invitations_collection(request, tender_id):
    if request.method == "GET":
        return invitation_list(request, tender_id)
    if request.method == "POST":
        return invitation_create(request, tender_id)
    return json_error("Method Not Allowed", 405)


@api_view(methods=("POST",), module="tender", level="write", idempotent=True)
def invitation_revoke(request, tender_id, invitation_id):
    return invitations.revoke(Ctx.from_request(request), tender_id, invitation_id)


@api_view(methods=("POST",), module="tender", level="write", idempotent=True)
def invitation_reissue(request, tender_id, invitation_id):
    return invitations.reissue(Ctx.from_request(request), tender_id, invitation_id)


@api_view(methods=("POST",), module="tender", level="write", idempotent=True)
def invitation_reset_device(request, tender_id, invitation_id):
    return invitations.reset_device(Ctx.from_request(request), tender_id, invitation_id)


@api_view(methods=("GET",), module="tender", level="read")
def invitation_events(request, tender_id, invitation_id):
    """Журнал портала приглашения (T3.2): привязки, отказы, предложения."""
    return invitations.events(Ctx.from_request(request), tender_id, invitation_id)
