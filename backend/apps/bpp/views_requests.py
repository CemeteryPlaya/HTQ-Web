"""Ручки заявки на закупку и плана закупок — подмодуль ``bpp_requests``
(ТЗ §07, §08, §23; B2.2, B2.3).

Каждая — под гейтом модуля ``bpp`` с явным уровнем; права тоньше уровня,
авторство и видимость проверяют сервисы. Записывающие ручки идемпотентны
(``Idempotency-Key``, AC-013). Согласование — ручки ``signoff``.
"""

from __future__ import annotations

from htqweb.http import api_view, json_error

from .schemas import requests as schemas
from .services.actor import Actor
from .services.core import export
from .services.core import printing
from .services.params import int_param
from .services.requests import files as files_service
from .services.requests import printing as request_printing
from .services.requests import read
from .services.requests import requests as service


def _card(request, req) -> dict:
    return read.card(Actor(request), req)


def _list_param(request, name: str) -> list[str]:
    return [value for value in request.GET.getlist(name) if value]


EXPORT_COLUMNS = (
    export.Column("number", "Номер"),
    export.Column("status", "Статус"),
    export.Column("created_at", "Дата создания", kind="date"),
    export.Column("author", "Автор"),
    export.Column("project", "Проект"),
    export.Column("article", "Статья бюджета"),
    export.Column("purchase_type", "Тип закупки"),
    export.Column("need_date", "Дата потребности", kind="date"),
    export.Column("total_amount", "Сумма", kind="money"),
    export.Column("currency_code", "Валюта"),
    export.Column("current_holder", "Сейчас у"),
)


@api_view(methods=("GET",), module="bpp", level="read")
def request_list(request):
    params = request.GET
    filters = {
        "statuses": _list_param(request, "status"),
        "project_ids": _list_param(request, "project_id"),
        "article_ids": _list_param(request, "article_id"),
        "author_id": int_param(params, "author_id"),
        "created_from": params.get("created_from") or None,
        "created_to": params.get("created_to") or None,
        "search": params.get("search") or None,
        "awaiting_me": params.get("awaiting_me") == "1",
    }
    actor = Actor(request)
    if params.get("format") == "xlsx":
        # Та же выборка, что у страницы, без пагинации; права заказчика
        # едут в пересборку фоновой выгрузки (у задачи нет запроса).
        kwargs = {**actor.export_identity(), "filters": filters}
        return export.respond(
            request, name="Заявки на закупку", columns=EXPORT_COLUMNS,
            rows=read.export_rows(**kwargs), count=read.export_count(**kwargs),
            rebuild=(read.EXPORT_REBUILD_PATH, kwargs))
    return read.registry(actor, filters=filters,
                         page=int_param(params, "page", 1, minimum=1),
                         page_size=int_param(params, "page_size", 50))


@api_view(methods=("POST",), module="bpp", level="write", body=schemas.RequestCreate,
          status=201, idempotent=True)
def request_create(request, data):
    return _card(request, service.create_draft(Actor(request), data.model_dump()))


def requests_collection(request):
    if request.method == "GET":
        return request_list(request)
    if request.method == "POST":
        return request_create(request)
    return json_error("Method Not Allowed", 405)


@api_view(methods=("GET",), module="bpp", level="read")
def request_get(request, request_id):
    actor = Actor(request)
    return read.card(actor, service.get_visible(actor, request_id))


@api_view(methods=("PATCH",), module="bpp", level="write", body=schemas.RequestUpdate,
          idempotent=True)
def request_patch(request, request_id, data):
    actor = Actor(request)
    service.get_visible(actor, request_id)
    sent = data.model_dump(exclude_unset=True)
    version = sent.pop("version", None)
    return _card(request, service.update_draft(actor, request_id, expected_version=version,
                                               data=sent))


@api_view(methods=("DELETE",), module="bpp", level="write", idempotent=True)
def request_delete(request, request_id):
    actor = Actor(request)
    service.get_visible(actor, request_id)
    version = request.GET.get("version")
    service.delete_draft(actor, request_id, expected_version=int(version) if version else None)
    return {"deleted": True}


def request_detail(request, request_id):
    if request.method == "GET":
        return request_get(request, request_id)
    if request.method == "PATCH":
        return request_patch(request, request_id)
    if request.method == "DELETE":
        return request_delete(request, request_id)
    return json_error("Method Not Allowed", 405)


@api_view(methods=("POST",), module="bpp", level="write", body=schemas.VersionOnly,
          idempotent=True)
def request_submit(request, request_id, data):
    actor = Actor(request)
    service.get_visible(actor, request_id)
    return _card(request, service.submit(actor, request_id, expected_version=data.version))


@api_view(methods=("POST",), module="bpp", level="write", body=schemas.VersionOnly,
          idempotent=True)
def request_withdraw(request, request_id, data):
    actor = Actor(request)
    service.get_visible(actor, request_id)
    return _card(request, service.withdraw(actor, request_id, expected_version=data.version))


@api_view(methods=("POST",), module="bpp", level="write", body=schemas.WithComment,
          idempotent=True)
def request_cancel(request, request_id, data):
    actor = Actor(request)
    service.get_visible(actor, request_id)
    return _card(request, service.cancel(actor, request_id, expected_version=data.version,
                                         comment=data.comment))


@api_view(methods=("POST",), module="bpp", level="write", body=schemas.WithComment,
          idempotent=True)
def request_close_remainder(request, request_id, data):
    actor = Actor(request)
    service.get_visible(actor, request_id)
    return _card(request, service.close_remainder(
        actor, request_id, expected_version=data.version, comment=data.comment))


@api_view(methods=("POST",), module="bpp", level="write", status=201, idempotent=True)
def request_copy(request, request_id):
    return _card(request, service.copy(Actor(request), request_id))


@api_view(methods=("GET",), module="bpp", level="read")
def request_execution(request, request_id):
    actor = Actor(request)
    return read.execution(service.get_visible(actor, request_id))


@api_view(methods=("GET",), module="bpp", level="read")
def request_print(request, request_id):
    """Печатная форма заявки с листом согласования — PDF в браузере."""
    req = service.get_visible(Actor(request), request_id)
    return printing.pdf_response(request_printing.TEMPLATE, request_printing.context(req),
                                 filename=f"{req.number}.pdf")


# ── документы заявки ────────────────────────────────────────────────────

@api_view(methods=("GET",), module="bpp", level="read")
def request_files_list(request, request_id):
    return files_service.list_files(Actor(request), request_id)


@api_view(methods=("POST",), module="bpp", level="write", status=201, idempotent=True)
def request_files_upload(request, request_id):
    return files_service.attach(Actor(request), request_id, request.FILES.get("file"))


def request_files(request, request_id):
    if request.method == "GET":
        return request_files_list(request, request_id)
    if request.method == "POST":
        return request_files_upload(request, request_id)
    return json_error("Method Not Allowed", 405)


@api_view(methods=("POST",), module="bpp", level="write", status=201, idempotent=True)
def request_file_version(request, request_id, file_id):
    return files_service.replace(Actor(request), request_id, file_id,
                                 request.FILES.get("file"))


@api_view(methods=("GET",), module="bpp", level="read")
def request_file_link(request, request_id, file_id):
    """Ссылка на скачивание — на каждое скачивание своя, с записью в журнал
    (ТЗ §25.2)."""
    return files_service.link(Actor(request), request_id, file_id)
