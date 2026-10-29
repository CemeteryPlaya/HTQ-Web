"""Ручки чек-листов задачи (мастер-план канбана §6.3, этап S2). Логика и
права — ``services/checklist_service``; ответ — чек-лист целиком."""

from __future__ import annotations

from django.http import HttpResponse

from htqweb.http import api_view, json_error

from . import schemas
from .services import checklist_service


def _method_not_allowed(request):
    return json_error("Method Not Allowed", 405)


# ── чек-листы задачи ────────────────────────────────────────────────────

@api_view(methods=("GET",), module="tasks", level="read")
def _task_checklists_get(request, task_id: int):
    return checklist_service.list_checklists(task_id, request)


@api_view(methods=("POST",), body=schemas.ChecklistIn, status=201, module="tasks", level="write")
def _task_checklists_post(request, task_id: int, data: schemas.ChecklistIn):
    return checklist_service.create_checklist(task_id, request, data.title, data.template)


def task_checklists(request, task_id: int):
    if request.method == "GET":
        return _task_checklists_get(request, task_id=task_id)
    if request.method == "POST":
        return _task_checklists_post(request, task_id=task_id)
    return _method_not_allowed(request)


# ── чек-лист ────────────────────────────────────────────────────────────

@api_view(methods=("PATCH",), body=schemas.ChecklistPatch, module="tasks", level="write")
def _checklist_patch(request, checklist_id: int, data: schemas.ChecklistPatch):
    return checklist_service.update_checklist(
        checklist_id, request, title=data.title, move=data.move,
        before_id=data.before_id, after_id=data.after_id)


@api_view(methods=("DELETE",), module="tasks", level="write")
def _checklist_delete(request, checklist_id: int):
    checklist_service.delete_checklist(checklist_id, request)
    return HttpResponse(status=204)


def checklist_detail(request, checklist_id: int):
    if request.method == "PATCH":
        return _checklist_patch(request, checklist_id=checklist_id)
    if request.method == "DELETE":
        return _checklist_delete(request, checklist_id=checklist_id)
    return _method_not_allowed(request)


@api_view(methods=("POST",), body=schemas.ChecklistItemIn, status=201, module="tasks",
          level="write")
def checklist_items(request, checklist_id: int, data: schemas.ChecklistItemIn):
    return checklist_service.add_item(checklist_id, request, text=data.text,
                                      before_id=data.before_id, after_id=data.after_id)


# ── пункт ───────────────────────────────────────────────────────────────

@api_view(methods=("PATCH",), body=schemas.ChecklistItemPatch, module="tasks", level="write")
def _item_patch(request, item_id: int, data: schemas.ChecklistItemPatch):
    return checklist_service.update_item(
        item_id, request, text=data.text, is_done=data.is_done,
        checklist_id=data.checklist_id, move=data.move,
        before_id=data.before_id, after_id=data.after_id)


@api_view(methods=("DELETE",), module="tasks", level="write")
def _item_delete(request, item_id: int):
    return checklist_service.delete_item(item_id, request)


def checklist_item_detail(request, item_id: int):
    if request.method == "PATCH":
        return _item_patch(request, item_id=item_id)
    if request.method == "DELETE":
        return _item_delete(request, item_id=item_id)
    return _method_not_allowed(request)
