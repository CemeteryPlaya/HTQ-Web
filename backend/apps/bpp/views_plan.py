"""Ручки плана закупок — подмодуль ``bpp_requests``, путь ``/plan`` (ТЗ §08, B2.3).

Каждая — под гейтом модуля ``bpp`` с явным уровнем; кто что видит и может
выбрать, решает ``services/plan/service.py``.
"""

from __future__ import annotations

from htqweb.http import api_view

from .schemas import requests as schemas
from .services.actor import Actor
from .services.params import int_param
from .services.plan import service as plan_service


def _list_param(request, name: str) -> list[str]:
    return [value for value in request.GET.getlist(name) if value]


@api_view(methods=("GET",), module="bpp", level="read")
def plan_list(request):
    params = request.GET
    filters = {
        "project_ids": _list_param(request, "project_id"),
        "article_ids": _list_param(request, "article_id"),
        "name": params.get("name") or None,
        "search": params.get("search") or None,
        "purchase_type": params.get("purchase_type") or None,
        "need_from": params.get("need_from") or None,
        "need_to": params.get("need_to") or None,
        "overdue": params.get("overdue") == "1",
    }
    return plan_service.plan_items(
        Actor(request), role=params.get("role") or None, filters=filters,
        sort=params.get("sort") or "need_date",
        page=int_param(params, "page", 1, minimum=1),
        page_size=int_param(params, "page_size", 50))


@api_view(methods=("POST",), module="bpp", level="write", body=schemas.PlanValidate)
def plan_validate(request, data):
    return plan_service.validate_selection(
        Actor(request), [str(item_id) for item_id in data.item_ids], target=data.target,
        role=data.role)


@api_view(methods=("POST",), module="bpp", level="write", body=schemas.PlanReassign,
          idempotent=True)
def plan_reassign(request, data):
    moved = plan_service.reassign(Actor(request), [str(i) for i in data.item_ids],
                                  to_user_id=data.to_user_id)
    return {"moved": moved}
