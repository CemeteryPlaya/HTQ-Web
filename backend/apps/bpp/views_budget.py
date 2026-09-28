"""Ручки бюджета проекта — подмодуль ``bpp_budget`` (ТЗ §06, §23; B2.1).

Каждая — под гейтом модуля ``bpp`` с явным уровнем; права тоньше уровня
(узлы ``bpp.budgets``, ``bpp.budgets.approve``) и видимость проверяют
сервисы. Записывающие ручки идемпотентны (``Idempotency-Key``, D-29).
Диспетчеры — голые цепочки по ``request.method`` (сторож
``apps/access/tests/test_gate.py``).
"""

from __future__ import annotations

from htqweb.http import api_view, json_error

from .schemas import budget as schemas
from .services.actor import Actor
from .services.params import int_param
from .services.budget import balance as balance_service
from .services.budget import budgets as service
from .services.budget import read


def _card(request, budget) -> dict:
    actor = Actor(request)
    return read.card(actor, service.get_visible(actor, budget.pk))


@api_view(methods=("GET",), module="bpp", level="read")
def budget_list(request):
    params = request.GET
    return read.registry(Actor(request), status=params.get("status") or None,
                         project_id=params.get("project_id") or None,
                         page=int_param(params, "page", 1, minimum=1),
                         page_size=int_param(params, "page_size", 50))


@api_view(methods=("POST",), module="bpp", level="write", body=schemas.BudgetCreate,
          status=201, idempotent=True)
def budget_create(request, data):
    payload = data.model_dump()
    payload["lines"] = [line.model_dump() for line in data.lines]
    budget = service.create(Actor(request), **payload)
    return _card(request, budget)


def budgets(request):
    if request.method == "GET":
        return budget_list(request)
    if request.method == "POST":
        return budget_create(request)
    return json_error("Method Not Allowed", 405)


@api_view(methods=("GET",), module="bpp", level="read")
def budget_get(request, budget_id):
    actor = Actor(request)
    return read.card(actor, service.get_visible(actor, budget_id))


@api_view(methods=("PATCH",), module="bpp", level="write", body=schemas.BudgetUpdate,
          idempotent=True)
def budget_patch(request, budget_id, data):
    actor = Actor(request)
    service.get_visible(actor, budget_id)
    sent = data.model_dump(exclude_unset=True)
    if data.lines is not None:
        sent["lines"] = [line.model_dump() for line in data.lines]
    budget = service.update_draft(
        actor, budget_id, expected_version=sent.pop("version", None),
        currency=sent.get("currency"), date_from=sent.get("date_from"),
        date_to=sent.get("date_to"), lines=sent.get("lines"))
    return _card(request, budget)


@api_view(methods=("DELETE",), module="bpp", level="write", idempotent=True)
def budget_delete(request, budget_id):
    actor = Actor(request)
    service.get_visible(actor, budget_id)
    version = request.GET.get("version")
    service.delete_draft(actor, budget_id,
                         expected_version=int(version) if version else None)
    return {"deleted": True}


def budget_detail(request, budget_id):
    if request.method == "GET":
        return budget_get(request, budget_id)
    if request.method == "PATCH":
        return budget_patch(request, budget_id)
    if request.method == "DELETE":
        return budget_delete(request, budget_id)
    return json_error("Method Not Allowed", 405)


@api_view(methods=("POST",), module="bpp", level="write", body=schemas.VersionOnly,
          idempotent=True)
def budget_approve(request, budget_id, data):
    actor = Actor(request)
    service.get_visible(actor, budget_id)
    return _card(request, service.approve(actor, budget_id, expected_version=data.version))


@api_view(methods=("POST",), module="bpp", level="write", body=schemas.VersionOnly,
          idempotent=True)
def correction_start(request, budget_id, data):
    actor = Actor(request)
    service.get_visible(actor, budget_id)
    return _card(request, service.start_correction(actor, budget_id,
                                                   expected_version=data.version))


@api_view(methods=("PATCH",), module="bpp", level="write", body=schemas.CorrectionSave,
          idempotent=True)
def correction_save(request, budget_id, data):
    actor = Actor(request)
    service.get_visible(actor, budget_id)
    budget = service.save_correction(
        actor, budget_id, expected_version=data.version,
        lines=[line.model_dump() for line in data.lines], comment=data.comment)
    return _card(request, budget)


def correction(request, budget_id):
    if request.method == "POST":
        return correction_start(request, budget_id)
    if request.method == "PATCH":
        return correction_save(request, budget_id)
    return json_error("Method Not Allowed", 405)


@api_view(methods=("POST",), module="bpp", level="write", body=schemas.WithComment,
          idempotent=True)
def correction_approve(request, budget_id, data):
    actor = Actor(request)
    service.get_visible(actor, budget_id)
    return _card(request, service.approve_correction(
        actor, budget_id, expected_version=data.version, comment=data.comment))


@api_view(methods=("POST",), module="bpp", level="write", body=schemas.VersionOnly,
          idempotent=True)
def correction_cancel(request, budget_id, data):
    actor = Actor(request)
    service.get_visible(actor, budget_id)
    return _card(request, service.cancel_correction(actor, budget_id,
                                                    expected_version=data.version))


@api_view(methods=("POST",), module="bpp", level="write", body=schemas.WithComment,
          idempotent=True)
def budget_close(request, budget_id, data):
    actor = Actor(request)
    service.get_visible(actor, budget_id)
    return _card(request, service.close(actor, budget_id, expected_version=data.version,
                                        comment=data.comment))


@api_view(methods=("POST",), module="bpp", level="write", body=schemas.WithComment,
          idempotent=True)
def budget_reopen(request, budget_id, data):
    actor = Actor(request)
    service.get_visible(actor, budget_id)
    return _card(request, service.reopen(actor, budget_id, expected_version=data.version,
                                         comment=data.comment))


@api_view(methods=("GET",), module="bpp", level="read")
def budget_versions(request, budget_id):
    actor = Actor(request)
    return read.versions(actor, service.get_visible(actor, budget_id))


@api_view(methods=("GET",), module="bpp", level="read")
def budget_version(request, budget_id, version_no: int):
    actor = Actor(request)
    return read.version_snapshot(actor, service.get_visible(actor, budget_id), version_no)


@api_view(methods=("GET",), module="bpp", level="read")
def budget_lines(request):
    """GetBudgetLines (ТЗ §23) — строки проекта в группе роли, для формы заявки."""
    params = request.GET
    return read.lines_for_request(Actor(request), project_id=params.get("project_id"),
                                  role=params.get("role") or "")


@api_view(methods=("GET",), module="bpp", level="read")
def budget_balance(request):
    """GetBudgetBalance (ТЗ §23): остаток статьи по действующей версии."""
    params = request.GET
    actor = Actor(request)
    project_id, article_id = params.get("project_id"), params.get("article_id")
    read.require_article_visible(actor, project_id, article_id)
    exclude = params.get("exclude_request_id")
    return balance_service.balance(
        project_id, article_id,
        exclude_request_id=read.uuid_param(exclude, "exclude_request_id") if exclude else None)
