"""Ручки заявки тендерного модуля — реестр, карточка, черновик (T1.1; план
этапов 0–2, §3.4).

Каждая — под гейтом модуля ``tender`` с явным уровнем (чтение — ``read``,
запись — ``write``); узел ``tender.requests``, авторство и статус проверяет
сервис (``services/requests/crud.py``). Файлы ТЗ и чертежей — панель
``/api/files/v1/tender.request/<id>/files/`` (владелец в ``file_owners.py``),
своих ручек файлов у заявки нет.
"""

from __future__ import annotations

from htqweb.errors import DomainError
from htqweb.http import api_view, json_error

from . import schemas
from .services.requests import crud, form, submit


def _int(params, name: str, default: int, *, minimum: int = 1, maximum: int = 200) -> int:
    raw = params.get(name)
    if raw in (None, ""):
        return default
    try:
        value = int(raw)
    except ValueError:
        raise DomainError("E-VAL-01", f"Параметр {name} — целое число.",
                          fields=[{"field": name, "message": "Целое число"}]) from None
    return max(minimum, min(value, maximum))


@api_view(methods=("GET",), module="tender", level="read")
def request_list(request):
    params = request.GET
    return crud.registry(
        crud.Ctx.from_request(request),
        statuses=[s for s in params.getlist("status") if s],
        project_id=params.get("project_id") or None, query=(params.get("q") or "").strip(),
        page=_int(params, "page", 1, maximum=10**6), page_size=_int(params, "page_size", 50))


@api_view(methods=("POST",), module="tender", level="write", body=schemas.RequestCreate,
          status=201, idempotent=True)
def request_create(request, data):
    ctx = crud.Ctx.from_request(request)
    return crud.card(ctx, crud.create_draft(ctx, data.model_dump()))


def requests_collection(request):
    if request.method == "GET":
        return request_list(request)
    if request.method == "POST":
        return request_create(request)
    return json_error("Method Not Allowed", 405)


@api_view(methods=("GET",), module="tender", level="read")
def request_get(request, request_id):
    ctx = crud.Ctx.from_request(request)
    crud.require(ctx, "view")
    return crud.card(ctx, crud.get_visible(ctx, request_id))


@api_view(methods=("PATCH",), module="tender", level="write", body=schemas.RequestUpdate,
          idempotent=True)
def request_patch(request, request_id, data):
    ctx = crud.Ctx.from_request(request)
    sent = data.model_dump(exclude_unset=True)
    version = sent.pop("version", None)
    return crud.card(ctx, crud.update_draft(ctx, request_id, expected_version=version,
                                            data=sent))


@api_view(methods=("DELETE",), module="tender", level="write", idempotent=True)
def request_delete(request, request_id):
    raw = request.GET.get("version")
    version = _int(request.GET, "version", 0, minimum=0, maximum=2**31 - 1) if raw else None
    crud.delete_draft(crud.Ctx.from_request(request), request_id, expected_version=version)
    return {"deleted": True}


def request_detail(request, request_id):
    if request.method == "GET":
        return request_get(request, request_id)
    if request.method == "PATCH":
        return request_patch(request, request_id)
    if request.method == "DELETE":
        return request_delete(request, request_id)
    return json_error("Method Not Allowed", 405)


# ── отправка, отзыв, отмена, исключение части (T1.3) ────────────────────

@api_view(methods=("POST",), module="tender", level="write", body=schemas.RequestAction,
          idempotent=True)
def request_submit(request, request_id, data):
    ctx = crud.Ctx.from_request(request)
    return crud.card(ctx, submit.submit(ctx, request_id, expected_version=data.version))


@api_view(methods=("POST",), module="tender", level="write", body=schemas.RequestAction,
          idempotent=True)
def request_withdraw(request, request_id, data):
    ctx = crud.Ctx.from_request(request)
    return crud.card(ctx, submit.withdraw(ctx, request_id, expected_version=data.version))


@api_view(methods=("POST",), module="tender", level="write", body=schemas.RequestCancel,
          idempotent=True)
def request_cancel(request, request_id, data):
    ctx = crud.Ctx.from_request(request)
    return crud.card(ctx, submit.cancel(ctx, request_id, expected_version=data.version,
                                        comment=data.comment))


@api_view(methods=("POST",), module="tender", level="write", body=schemas.RequestAction,
          idempotent=True)
def request_part_exclude(request, request_id, part_id, data):
    ctx = crud.Ctx.from_request(request)
    return crud.card(ctx, submit.exclude_part(ctx, request_id, part_id,
                                              expected_version=data.version))


# ── подсказки формы (T1.3) ──────────────────────────────────────────────

@api_view(methods=("GET",), module="tender", level="read")
def request_budget(request):
    params = request.GET
    return form.budget(crud.Ctx.from_request(request), project_id=params.get("project_id"),
                       article_id=params.get("article_id"), role=params.get("role"))


@api_view(methods=("GET",), module="tender", level="read")
def request_articles(request):
    params = request.GET
    return form.articles(crud.Ctx.from_request(request),
                         project_id=params.get("project_id"), role=params.get("role"))


@api_view(methods=("GET",), module="tender", level="read")
def request_projects(request):
    params = request.GET
    return form.project_list(crud.Ctx.from_request(request),
                             query=(params.get("q") or "").strip(), role=params.get("role"))
