"""Ручки своих полей досок (решение K-35, канбан, этап S3): определения у
досок отделов и проектов, значение поля у задачи. Логика и права —
``services/board_fields``; шаблоны чек-листов — в настройках доски
(``views_boards``)."""

from __future__ import annotations

from django.http import HttpResponse

from htqweb.http import api_view, json_error

from . import schemas
from .services import board_fields
from .services import board_service


def _method_not_allowed(request):
    return json_error("Method Not Allowed", 405)


# ── поля доски отдела ───────────────────────────────────────────────────

@api_view(methods=("GET",), module="tasks", level="read")
def _department_fields_get(request, department_id: int):
    return board_fields.list_fields(board_service.department(request, department_id))


@api_view(methods=("POST",), body=schemas.BoardFieldIn, status=201, module="tasks",
          level="write")
def _department_fields_post(request, department_id: int, data: schemas.BoardFieldIn):
    return board_fields.create_field(request, board_service.department(request, department_id),
                                     data)


def department_fields(request, department_id: int):
    if request.method == "GET":
        return _department_fields_get(request, department_id=department_id)
    if request.method == "POST":
        return _department_fields_post(request, department_id=department_id)
    return _method_not_allowed(request)


# ── поля доски проекта ──────────────────────────────────────────────────

@api_view(methods=("GET",), module="tasks", level="read")
def _project_fields_get(request, project_id: int):
    return board_fields.list_fields(board_service.project(request, project_id))


@api_view(methods=("POST",), body=schemas.BoardFieldIn, status=201, module="tasks",
          level="write")
def _project_fields_post(request, project_id: int, data: schemas.BoardFieldIn):
    return board_fields.create_field(request, board_service.project(request, project_id), data)


def project_fields(request, project_id: int):
    if request.method == "GET":
        return _project_fields_get(request, project_id=project_id)
    if request.method == "POST":
        return _project_fields_post(request, project_id=project_id)
    return _method_not_allowed(request)


# ── поле ────────────────────────────────────────────────────────────────

@api_view(methods=("PATCH",), body=schemas.BoardFieldPatch, module="tasks", level="write")
def _field_patch(request, field_id: int, data: schemas.BoardFieldPatch):
    return board_fields.update_field(request, field_id, data)


@api_view(methods=("DELETE",), module="tasks", level="write")
def _field_delete(request, field_id: int):
    board_fields.delete_field(request, field_id)
    return HttpResponse(status=204)


def field_detail(request, field_id: int):
    if request.method == "PATCH":
        return _field_patch(request, field_id=field_id)
    if request.method == "DELETE":
        return _field_delete(request, field_id=field_id)
    return _method_not_allowed(request)


# ── значение поля у задачи ──────────────────────────────────────────────

@api_view(methods=("PUT",), body=schemas.TaskFieldValueIn, module="tasks", level="write")
def task_field_value(request, task_id: int, field_id: int, data: schemas.TaskFieldValueIn):
    return board_fields.set_value(request, task_id, field_id, data.value)
