"""Ручки канбан-досок: доски, перенос карточки, «просмотрено», настройки
колонок (мастер-план §6.1–6.2, этап S1), лента карточки и выключатель
уведомлений доски (§6.4, K-30, этап S2). Логика — ``services/board_service``
и ``services/feed_service``.

Личная доска — без параметров пути (§5.4): владелец всегда из токена.
"""

from __future__ import annotations

from django.http import HttpResponse

from htqweb.http import api_view, json_error

from . import schemas
from .services import board_service
from .services import feed_service
from .services import people


def _method_not_allowed(request):
    return json_error("Method Not Allowed", 405)


# ── список досок ────────────────────────────────────────────────────────

@api_view(methods=("GET",), module="tasks", level="read")
def boards_collection(request):
    return board_service.list_boards(request)


@api_view(methods=("GET",), module="tasks", level="read")
def boards_notifications(request):
    """Доски, по которым у меня выключены уведомления (K-30)."""
    return board_service.muted_boards(request)


# ── личная доска ────────────────────────────────────────────────────────

@api_view(methods=("GET",), module="tasks", level="read")
def personal_board(request):
    return board_service.build_board(request, board_service.personal(request),
                                     board_service.Filters.from_query(request.GET))


@api_view(methods=("GET",), module="tasks", level="read")
def personal_summary(request):
    return board_service.personal_summary(request)


@api_view(methods=("GET",), module="tasks", level="read")
def _personal_settings_get(request):
    return board_service.settings_payload(board_service.personal(request))


@api_view(methods=("PUT",), body=schemas.BoardSettingsIn, module="tasks", level="write")
def _personal_settings_put(request, data: schemas.BoardSettingsIn):
    return board_service.save_settings(request, board_service.personal(request), data)


def personal_settings(request):
    if request.method == "GET":
        return _personal_settings_get(request)
    if request.method == "PUT":
        return _personal_settings_put(request)
    return _method_not_allowed(request)


# ── доска отдела ────────────────────────────────────────────────────────

@api_view(methods=("GET",), module="tasks", level="read")
def department_board(request, department_id: int):
    return board_service.build_board(request, board_service.department(request, department_id),
                                     board_service.Filters.from_query(request.GET))


@api_view(methods=("GET",), module="tasks", level="read")
def _department_settings_get(request, department_id: int):
    return board_service.settings_payload(board_service.department(request, department_id))


@api_view(methods=("PUT",), body=schemas.BoardSettingsIn, module="tasks", level="write")
def _department_settings_put(request, department_id: int, data: schemas.BoardSettingsIn):
    board = board_service.department(request, department_id)
    return board_service.save_settings(request, board, data)


@api_view(methods=("PUT",), body=schemas.BoardNotificationsIn, module="tasks", level="write")
def department_notifications(request, department_id: int, data: schemas.BoardNotificationsIn):
    board = board_service.department(request, department_id)
    return board_service.set_notifications(request, board, data.enabled)


def department_settings(request, department_id: int):
    if request.method == "GET":
        return _department_settings_get(request, department_id=department_id)
    if request.method == "PUT":
        return _department_settings_put(request, department_id=department_id)
    return _method_not_allowed(request)


# ── доска проекта ───────────────────────────────────────────────────────

@api_view(methods=("GET",), module="tasks", level="read")
def project_board(request, project_id: int):
    return board_service.build_board(request, board_service.project(request, project_id),
                                     board_service.Filters.from_query(request.GET))


@api_view(methods=("GET",), module="tasks", level="read")
def _project_settings_get(request, project_id: int):
    return board_service.settings_payload(board_service.project(request, project_id))


@api_view(methods=("PUT",), body=schemas.BoardSettingsIn, module="tasks", level="write")
def _project_settings_put(request, project_id: int, data: schemas.BoardSettingsIn):
    board = board_service.project(request, project_id)
    return board_service.save_settings(request, board, data)


@api_view(methods=("PUT",), body=schemas.BoardNotificationsIn, module="tasks", level="write")
def project_notifications(request, project_id: int, data: schemas.BoardNotificationsIn):
    board = board_service.project(request, project_id)
    return board_service.set_notifications(request, board, data.enabled)


def project_settings(request, project_id: int):
    if request.method == "GET":
        return _project_settings_get(request, project_id=project_id)
    if request.method == "PUT":
        return _project_settings_put(request, project_id=project_id)
    return _method_not_allowed(request)


# ── карточка на доске ───────────────────────────────────────────────────

@api_view(methods=("POST",), body=schemas.CardMove, module="tasks", level="write")
def task_move(request, task_id: int, data: schemas.CardMove):
    return board_service.move(request, task_id, data)


@api_view(methods=("POST",), module="tasks", level="write")
def task_seen(request, task_id: int):
    board_service.mark_seen(request, task_id)
    return HttpResponse(status=204)


@api_view(methods=("GET",), module="tasks", level="read")
def task_feed(request, task_id: int):
    """Лента карточки (§6.4): `?details=0|1&before=<курсор>&limit=`."""
    raw_limit = request.GET.get("limit") or ""
    return feed_service.feed(task_id, request,
                             details=request.GET.get("details") in ("1", "true"),
                             before=request.GET.get("before"),
                             limit=int(raw_limit) if raw_limit.isdigit() else None)


@api_view(methods=("GET",), module="tasks", level="read")
def people_search(request):
    """Люди для окна карточки: `?query=` (от двух букв), `?limit=` (до 50) —
    действующие участники текущей компании."""
    raw_limit = request.GET.get("limit") or ""
    limit = min(int(raw_limit), 50) if raw_limit.isdigit() and int(raw_limit) > 0 else 20
    return people.search(request.GET.get("query") or "", limit)
