"""Ручки договора — подмодуль ``bpp_agreements`` (ТЗ §09, §23; B3.1).

Каждая — под гейтом модуля ``bpp`` с явным уровнем; права тоньше уровня,
авторство и видимость проверяют сервисы. Записывающие ручки идемпотентны
(``Idempotency-Key``, AC-013). Согласование — ручки ``signoff``.
"""

from __future__ import annotations

from htqweb.http import api_view, json_error

from .schemas import agreements as schemas
from .services.actor import Actor
from .services.agreements import agreements as service
from .services.agreements import read
from .services.core import export
from .services.params import int_param


def _card(request, agr, *, vat_warning: str | None = None) -> dict:
    return read.card(Actor(request), agr, vat_warning=vat_warning)


def _list_param(request, name: str) -> list[str]:
    return [value for value in request.GET.getlist(name) if value]


EXPORT_COLUMNS = (
    export.Column("number", "Номер"),
    export.Column("status", "Статус"),
    export.Column("ext_number", "Номер по документу"),
    export.Column("ext_date", "Дата договора", kind="date"),
    export.Column("name", "Наименование"),
    export.Column("counterparty_name", "Контрагент"),
    export.Column("project_code", "Проект"),
    export.Column("article_name", "Статья бюджета"),
    export.Column("amount", "Сумма", kind="money"),
    export.Column("remaining", "Остаток по договору", kind="money"),
    export.Column("currency_code", "Валюта"),
    export.Column("valid_to", "Срок действия по", kind="date"),
    export.Column("author_name", "Автор"),
)


@api_view(methods=("GET",), module="bpp", level="read")
def agreement_list(request):
    params = request.GET
    filters = {
        "statuses": _list_param(request, "status"),
        "project_ids": _list_param(request, "project_id"),
        "article_ids": _list_param(request, "article_id"),
        "counterparty_id": params.get("counterparty_id") or None,
        "date_from": params.get("date_from") or None,
        "date_to": params.get("date_to") or None,
        "search": params.get("search") or None,
        "awaiting_me": params.get("awaiting_me") == "1",
    }
    actor = Actor(request)
    if params.get("format") == "xlsx":
        kwargs = {**actor.export_identity(), "filters": filters}
        return export.respond(
            request, name="Договоры", columns=EXPORT_COLUMNS,
            rows=read.export_rows(**kwargs), count=read.export_count(**kwargs),
            rebuild=(read.EXPORT_REBUILD_PATH, kwargs))
    return read.registry(actor, filters=filters,
                         page=int_param(params, "page", 1, minimum=1),
                         page_size=int_param(params, "page_size", 50))


@api_view(methods=("POST",), module="bpp", level="write", body=schemas.AgreementFromPlan,
          status=201, idempotent=True)
def agreement_create(request, data):
    agr = service.create_from_plan(Actor(request), [str(i) for i in data.item_ids],
                                   role=data.role)
    return _card(request, agr)


def agreements_collection(request):
    if request.method == "GET":
        return agreement_list(request)
    if request.method == "POST":
        return agreement_create(request)
    return json_error("Method Not Allowed", 405)


@api_view(methods=("GET",), module="bpp", level="read")
def agreement_get(request, agreement_id):
    actor = Actor(request)
    return read.card(actor, service.get_visible(actor, agreement_id))


@api_view(methods=("PATCH",), module="bpp", level="write", body=schemas.AgreementUpdate,
          idempotent=True)
def agreement_patch(request, agreement_id, data):
    actor = Actor(request)
    service.get_visible(actor, agreement_id)
    sent = data.model_dump(exclude_unset=True)
    version = sent.pop("version", None)
    if "counterparty_id" in sent and sent["counterparty_id"] is not None:
        sent["counterparty_id"] = str(sent["counterparty_id"])
    agr, warning = service.update_draft(actor, agreement_id, expected_version=version,
                                        data=sent)
    return _card(request, agr, vat_warning=warning)


@api_view(methods=("DELETE",), module="bpp", level="write", idempotent=True)
def agreement_delete(request, agreement_id):
    actor = Actor(request)
    service.get_visible(actor, agreement_id)
    version = request.GET.get("version")
    service.delete_draft(actor, agreement_id, expected_version=int(version) if version else None)
    return {"deleted": True}


def agreement_detail(request, agreement_id):
    if request.method == "GET":
        return agreement_get(request, agreement_id)
    if request.method == "PATCH":
        return agreement_patch(request, agreement_id)
    if request.method == "DELETE":
        return agreement_delete(request, agreement_id)
    return json_error("Method Not Allowed", 405)


@api_view(methods=("POST",), module="bpp", level="write", body=schemas.AgreementSubmit,
          idempotent=True)
def agreement_submit(request, agreement_id, data):
    actor = Actor(request)
    service.get_visible(actor, agreement_id)
    return _card(request, service.submit(actor, agreement_id, expected_version=data.version,
                                         counterparty_confirmed=data.counterparty_confirmed))


@api_view(methods=("POST",), module="bpp", level="write", body=schemas.VersionOnly,
          idempotent=True)
def agreement_withdraw(request, agreement_id, data):
    actor = Actor(request)
    service.get_visible(actor, agreement_id)
    return _card(request, service.withdraw(actor, agreement_id, expected_version=data.version))


@api_view(methods=("POST",), module="bpp", level="write", body=schemas.VersionOnly,
          idempotent=True)
def agreement_fulfil(request, agreement_id, data):
    actor = Actor(request)
    service.get_visible(actor, agreement_id)
    return _card(request, service.fulfil(actor, agreement_id, expected_version=data.version))


@api_view(methods=("POST",), module="bpp", level="write", body=schemas.WithComment,
          idempotent=True)
def agreement_terminate(request, agreement_id, data):
    actor = Actor(request)
    service.get_visible(actor, agreement_id)
    return _card(request, service.terminate(actor, agreement_id, expected_version=data.version,
                                            comment=data.comment))


@api_view(methods=("POST",), module="bpp", level="write", status=201, idempotent=True)
def agreement_supplement(request, agreement_id):
    return _card(request, service.create_supplement(Actor(request), agreement_id))


@api_view(methods=("GET",), module="bpp", level="read")
def agreement_execution(request, agreement_id):
    actor = Actor(request)
    return read.execution(service.get_visible(actor, agreement_id))


@api_view(methods=("GET",), module="bpp", level="read")
def agreement_search(request):
    """Договоры для счёта (BR-046, AC-007)."""
    params = request.GET
    return {"items": read.search_for_invoice(
        Actor(request), project_id=params.get("project_id"),
        article_id=params.get("article_id"), query=params.get("q") or "")}
