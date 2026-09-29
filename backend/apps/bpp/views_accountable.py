"""Ручки подотчётных средств — подмодуль ``bpp_accountable`` (задача B4.1).

Каждая — под гейтом модуля ``bpp`` с явным уровнем; узлы
``bpp.accountable`` / ``bpp.accountable.payment`` и принадлежность проверяет
сервис. Согласование заявки и отчётов — ручки ``signoff``.
"""

from __future__ import annotations

from htqweb.errors import DomainError
from htqweb.http import api_view, json_error

from .schemas import accountable as schemas
from .services.accountable import accountable as service
from .services.accountable import read
from .services.actor import Actor
from .services.core import export
from .services.params import int_param


def _card(request, req) -> dict:
    actor = Actor(request)
    return service.card(actor, service.get_visible(actor, req.pk))


def _list_param(request, name: str) -> list[str]:
    return [value for value in request.GET.getlist(name) if value]


EXPORT_COLUMNS = (
    export.Column("number", "Номер"),
    export.Column("status", "Статус"),
    export.Column("created_at", "Дата создания", kind="date"),
    export.Column("accountable", "Подотчётное лицо"),
    export.Column("project", "Проект"),
    export.Column("article", "Статья бюджета"),
    export.Column("goal", "Цель"),
    export.Column("amount", "Сумма", kind="money"),
    export.Column("currency", "Валюта"),
    export.Column("reported_amount", "Подтверждено отчётами", kind="money"),
    export.Column("current_holder", "Сейчас у"),
)


@api_view(methods=("GET",), module="bpp", level="read")
def accountable_list(request):
    params = request.GET
    filters = {
        "statuses": _list_param(request, "status"),
        "project_ids": _list_param(request, "project_id"),
        "article_ids": _list_param(request, "article_id"),
        "date_from": params.get("date_from") or None,
        "date_to": params.get("date_to") or None,
        "search": params.get("search") or None,
        "awaiting_me": params.get("awaiting_me") == "1",
    }
    actor = Actor(request)
    if params.get("format") == "xlsx":
        kwargs = {**actor.export_identity(), "filters": filters}
        return export.respond(
            request, name="Подотчётные средства", columns=EXPORT_COLUMNS,
            rows=read.export_rows(**kwargs), count=read.export_count(**kwargs),
            rebuild=(read.EXPORT_REBUILD_PATH, kwargs))
    return read.registry(actor, filters=filters,
                         page=int_param(params, "page", 1, minimum=1),
                         page_size=int_param(params, "page_size", 50))


@api_view(methods=("POST",), module="bpp", level="write", body=schemas.AccountableCreate,
          status=201, idempotent=True)
def accountable_create(request, data):
    return _card(request, service.create(Actor(request), **data.model_dump()))


def accountable_collection(request):
    if request.method == "GET":
        return accountable_list(request)
    if request.method == "POST":
        return accountable_create(request)
    return json_error("Method Not Allowed", 405)


@api_view(methods=("GET",), module="bpp", level="read")
def accountable_get(request, request_id):
    actor = Actor(request)
    return service.card(actor, service.get_visible(actor, request_id))


@api_view(methods=("PATCH",), module="bpp", level="write", body=schemas.AccountableUpdate,
          idempotent=True)
def accountable_patch(request, request_id, data):
    actor = Actor(request)
    service.get_visible(actor, request_id)
    sent = data.model_dump(exclude_unset=True)
    return _card(request, service.update_draft(actor, request_id,
                                               expected_version=sent.pop("version", None),
                                               data=sent))


@api_view(methods=("DELETE",), module="bpp", level="write", idempotent=True)
def accountable_delete(request, request_id):
    actor = Actor(request)
    service.get_visible(actor, request_id)
    version = request.GET.get("version")
    service.delete_draft(actor, request_id,
                         expected_version=int(version) if version and version.isdigit() else None)
    return {"deleted": True}


def accountable_detail(request, request_id):
    if request.method == "GET":
        return accountable_get(request, request_id)
    if request.method == "PATCH":
        return accountable_patch(request, request_id)
    if request.method == "DELETE":
        return accountable_delete(request, request_id)
    return json_error("Method Not Allowed", 405)


@api_view(methods=("POST",), module="bpp", level="write", body=schemas.VersionOnly,
          idempotent=True)
def accountable_submit(request, request_id, data):
    actor = Actor(request)
    service.get_visible(actor, request_id)
    return _card(request, service.submit(actor, request_id, expected_version=data.version))


@api_view(methods=("POST",), module="bpp", level="write", body=schemas.VersionOnly,
          idempotent=True)
def accountable_mark_paid(request, request_id, data):
    actor = Actor(request)
    service.get_visible(actor, request_id)
    return _card(request, service.mark_paid(actor, request_id, expected_version=data.version))


@api_view(methods=("POST",), module="bpp", level="write", status=201, idempotent=True)
def accountable_add_report(request, request_id):
    """Авансовый отчёт: multipart — ``expense_name``, ``amount``, ``file``."""
    actor = Actor(request)
    service.get_visible(actor, request_id)
    try:
        amount = request.POST.get("amount") or "0"
        report = service.add_report(actor, request_id,
                                    expense_name=request.POST.get("expense_name", ""),
                                    amount=amount, upload=request.FILES.get("file"))
    except ArithmeticError as exc:
        raise DomainError("E-VAL-01", "Сумма указана неверно.",
                          fields=[{"field": "amount", "message": "Число"}]) from exc
    return service.serialize_report(report, actor)


@api_view(methods=("POST",), module="bpp", level="write", idempotent=True)
def report_submit(request, report_id):
    actor = Actor(request)
    service.get_visible_report(actor, report_id)
    return service.serialize_report(service.submit_report(actor, report_id), actor)


@api_view(methods=("GET",), module="bpp", level="read")
def report_file_link(request, report_id):
    return service.report_file_link(Actor(request), report_id)
