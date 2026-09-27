"""Регистрация документов модуля БЗО в движке согласования ``signoff``.

Зовётся из ``BppConfig.ready()``. Движок не знает таблиц модуля: статус
документа он меняет только через эти колбэки, а ключ документа передаёт в
типе ключа модели — ``uuid.UUID`` (B0.1, ``registry.native_id``).

Маршрут не зашит в код: его заводит команда ``bpp_setup_routes`` (по
должностям), флаги маршрутов БЗО — самосогласование, комментарий ≥ 10,
ленивое разрешение исполнителей (D-21).

Здесь же — проверки доступа к «Истории изменений» (``audit.
register_history_access``): журнал документа читает тот, кто видит сам
документ.
"""

from __future__ import annotations

from apps.bpp.models import Budget, PurchaseRequest, PurchaseType
from apps.bpp.services.actor import Actor
from apps.bpp.services.budget import budgets as budget_service
from apps.bpp.services.core import audit
from apps.bpp.services.money import fmt
from apps.bpp.services.requests import requests as request_service
from apps.project import interface as projects
from apps.refdata import interface as refdata
from apps.signoff import interface as signoff


def _describe_request(subject_id) -> dict | None:
    req = PurchaseRequest.objects.filter(pk=subject_id).first()
    if req is None:
        return None
    code = (projects.project_brief([str(req.project_id)]).get(str(req.project_id))
            or {}).get("code", "")
    return {
        "title": f"Заявка {req.number} на {fmt(req.total_amount, req.currency)}"
                 + (f" по проекту {code}" if code else ""),
        "url": f"/bpp/requests/{req.pk}",
    }


def _request_facts(subject_id) -> dict:
    req = PurchaseRequest.objects.filter(pk=subject_id).first()
    if req is None:
        return {}
    group = ""
    if req.article_id:
        brief = refdata.article_brief([str(req.article_id)]).get(str(req.article_id))
        groups = {g["id"]: g["code"] for g in refdata.article_groups()}
        group = groups.get(brief["group_id"], "") if brief else ""
    return {"amount": req.total_amount, "currency": req.currency,
            "purchase_type": req.purchase_type, "article_group": group,
            "initiator_role": req.initiator_role}


def _request_fact_fields() -> list[dict]:
    return [
        {"key": "amount", "label": "Сумма заявки", "type": "number"},
        {"key": "currency", "label": "Валюта", "type": "string"},
        {"key": "purchase_type", "label": "Вид закупки", "type": "choice",
         "options": [{"value": v, "label": label} for v, label in PurchaseType.choices]},
        {"key": "article_group", "label": "Группа статей", "type": "choice",
         "options": [{"value": g["code"], "label": g["name"]}
                     for g in refdata.article_groups()]},
        {"key": "initiator_role", "label": "Роль инициатора", "type": "choice",
         "options": [{"value": "sn", "label": "Снабженец"},
                     {"value": "pm", "label": "Руководитель проекта"}]},
    ]


def _history_of(model, can_view):
    def check(request, object_id: str) -> bool:
        obj = model.objects.filter(pk=object_id).first()
        return obj is not None and can_view(Actor(request), obj)
    return check


def _valid_uuid_guard(check):
    """Ключ из URL не UUID — нет такого объекта, а не 500."""
    def guarded(request, object_id: str) -> bool:
        import uuid

        try:
            uuid.UUID(str(object_id))
        except ValueError:
            return False
        return check(request, object_id)
    return guarded


def register() -> None:
    signoff.register_subject(
        PurchaseRequest.SIGNOFF_SUBJECT_TYPE,
        label="Заявка на закупку",
        model=PurchaseRequest,
        on_started=request_service.on_started,
        on_approved=request_service.on_approved,
        on_rejected=request_service.on_rejected,
        on_rework=request_service.on_rework,
        on_cancelled=request_service.on_cancelled,
        describe=_describe_request,
        facts=_request_facts,
        fact_fields=_request_fact_fields,
    )
    audit.register_history_access(
        Budget._meta.label_lower,
        _valid_uuid_guard(_history_of(Budget, budget_service.can_view)))
    audit.register_history_access(
        PurchaseRequest._meta.label_lower,
        _valid_uuid_guard(_history_of(PurchaseRequest, request_service.can_view)))
