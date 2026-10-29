"""Ручки автоматизации досок (решения K-36…K-40, этап S4): каталог для
конструктора, автоматизации доски и их журнал, кнопки, шаблон процесса.
Логика и права — ``services/automation/*``."""

from __future__ import annotations

from django.http import HttpResponse

from htqweb.http import api_view, json_error

from . import schemas
from .services import board_service
from .services.automation import buttons, catalog, presets, rules, suggestions


def _method_not_allowed(request):
    return json_error("Method Not Allowed", 405)


def _int(raw: str | None) -> int | None:
    return int(raw) if raw and raw.isdigit() else None


@api_view(methods=("GET",), module="tasks", level="read")
def automation_catalog(request):
    return catalog.describe()


# ── автоматизации доски отдела ──────────────────────────────────────────

@api_view(methods=("GET",), module="tasks", level="read")
def _department_automation_get(request, department_id: int):
    return rules.list_rules(board_service.department(request, department_id),
                            request.GET.get("kind") or None)


@api_view(methods=("POST",), body=schemas.AutomationIn, status=201, module="tasks",
          level="write")
def _department_automation_post(request, department_id: int, data: schemas.AutomationIn):
    return rules.create(request, board_service.department(request, department_id), data)


def department_automation(request, department_id: int):
    if request.method == "GET":
        return _department_automation_get(request, department_id=department_id)
    if request.method == "POST":
        return _department_automation_post(request, department_id=department_id)
    return _method_not_allowed(request)


@api_view(methods=("GET",), module="tasks", level="read")
def department_automation_runs(request, department_id: int):
    return rules.runs(request, board_service.department(request, department_id),
                      rule_id=_int(request.GET.get("rule")),
                      problems=request.GET.get("problems") in ("1", "true"),
                      before=_int(request.GET.get("before")),
                      limit=_int(request.GET.get("limit")))


@api_view(methods=("POST",), module="tasks", level="write")
def department_button(request, department_id: int, rule_id: int):
    return buttons.press_board(request, board_service.department(request, department_id), rule_id)


@api_view(methods=("GET",), module="tasks", level="read")
def department_suggestions(request, department_id: int):
    return suggestions.for_user(request, board_service.department(request, department_id))


@api_view(methods=("POST",), body=schemas.SuggestionDismissIn, status=204, module="tasks",
          level="write")
def department_suggestion_dismiss(request, department_id: int, data: schemas.SuggestionDismissIn):
    suggestions.dismiss(request, board_service.department(request, department_id), data.key)
    return HttpResponse(status=204)


@api_view(methods=("POST",), body=schemas.BoardPresetIn, module="tasks", level="write")
def department_preset(request, department_id: int, data: schemas.BoardPresetIn):
    return presets.apply_from_request(request, board_service.department(request, department_id),
                                      data.preset, dry_run=data.dry_run)


# ── автоматизации доски проекта ─────────────────────────────────────────

@api_view(methods=("GET",), module="tasks", level="read")
def _project_automation_get(request, project_id: int):
    return rules.list_rules(board_service.project(request, project_id),
                            request.GET.get("kind") or None)


@api_view(methods=("POST",), body=schemas.AutomationIn, status=201, module="tasks",
          level="write")
def _project_automation_post(request, project_id: int, data: schemas.AutomationIn):
    return rules.create(request, board_service.project(request, project_id), data)


def project_automation(request, project_id: int):
    if request.method == "GET":
        return _project_automation_get(request, project_id=project_id)
    if request.method == "POST":
        return _project_automation_post(request, project_id=project_id)
    return _method_not_allowed(request)


@api_view(methods=("GET",), module="tasks", level="read")
def project_automation_runs(request, project_id: int):
    return rules.runs(request, board_service.project(request, project_id),
                      rule_id=_int(request.GET.get("rule")),
                      problems=request.GET.get("problems") in ("1", "true"),
                      before=_int(request.GET.get("before")),
                      limit=_int(request.GET.get("limit")))


@api_view(methods=("POST",), module="tasks", level="write")
def project_button(request, project_id: int, rule_id: int):
    return buttons.press_board(request, board_service.project(request, project_id), rule_id)


@api_view(methods=("GET",), module="tasks", level="read")
def project_suggestions(request, project_id: int):
    return suggestions.for_user(request, board_service.project(request, project_id))


@api_view(methods=("POST",), body=schemas.SuggestionDismissIn, status=204, module="tasks",
          level="write")
def project_suggestion_dismiss(request, project_id: int, data: schemas.SuggestionDismissIn):
    suggestions.dismiss(request, board_service.project(request, project_id), data.key)
    return HttpResponse(status=204)


@api_view(methods=("POST",), body=schemas.BoardPresetIn, module="tasks", level="write")
def project_preset(request, project_id: int, data: schemas.BoardPresetIn):
    return presets.apply_from_request(request, board_service.project(request, project_id),
                                      data.preset, dry_run=data.dry_run)


# ── автоматизация ───────────────────────────────────────────────────────

@api_view(methods=("PATCH",), body=schemas.AutomationPatch, module="tasks", level="write")
def _automation_patch(request, rule_id: int, data: schemas.AutomationPatch):
    return rules.update(request, rule_id, data)


@api_view(methods=("DELETE",), module="tasks", level="write")
def _automation_delete(request, rule_id: int):
    rules.delete(request, rule_id)
    return HttpResponse(status=204)


def automation_detail(request, rule_id: int):
    if request.method == "PATCH":
        return _automation_patch(request, rule_id=rule_id)
    if request.method == "DELETE":
        return _automation_delete(request, rule_id=rule_id)
    return _method_not_allowed(request)


@api_view(methods=("POST",), status=201, module="tasks", level="write")
def automation_copy(request, rule_id: int):
    return rules.copy(request, rule_id)


# ── кнопка на карточке ──────────────────────────────────────────────────

@api_view(methods=("POST",), module="tasks", level="write")
def task_button(request, task_id: int, rule_id: int):
    return buttons.press_card(request, task_id, rule_id)
