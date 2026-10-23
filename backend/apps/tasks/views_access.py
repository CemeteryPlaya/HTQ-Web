"""Ручки запросов доступа к задаче и панели «Запросы» (решения K-31, K-32;
мастер-план канбана §6.2, этап S2). Логика и права — ``services/access_requests``."""

from __future__ import annotations

from django.http import HttpResponse

from htqweb.http import api_view, json_error

from . import schemas
from .services import access_requests


def _method_not_allowed(request):
    return json_error("Method Not Allowed", 405)


# ── запросы к задаче ────────────────────────────────────────────────────

@api_view(methods=("GET",), module="tasks", level="read")
def _task_requests_get(request, task_id: int):
    return access_requests.for_task(task_id, request)


@api_view(methods=("POST",), body=schemas.AccessRequestIn, status=201, module="tasks",
          level="write")
def _task_requests_post(request, task_id: int, data: schemas.AccessRequestIn):
    return access_requests.request_access(task_id, request, kind=data.kind,
                                          comment=data.comment.strip())


def task_access_requests(request, task_id: int):
    if request.method == "GET":
        return _task_requests_get(request, task_id=task_id)
    if request.method == "POST":
        return _task_requests_post(request, task_id=task_id)
    return _method_not_allowed(request)


# ── решение и отзыв ─────────────────────────────────────────────────────

@api_view(methods=("POST",), body=schemas.AccessApproveIn, module="tasks", level="write")
def access_request_approve(request, request_id: int, data: schemas.AccessApproveIn):
    return access_requests.decide(request_id, request, approve=True, mode=data.mode,
                                  comment=data.comment.strip())


@api_view(methods=("POST",), body=schemas.AccessRejectIn, module="tasks", level="write")
def access_request_reject(request, request_id: int, data: schemas.AccessRejectIn):
    return access_requests.decide(request_id, request, approve=False,
                                  comment=data.comment.strip())


@api_view(methods=("DELETE",), module="tasks", level="write")
def access_request_cancel(request, request_id: int):
    access_requests.cancel(request_id, request)
    return HttpResponse(status=204)


# ── панель «Запросы» ────────────────────────────────────────────────────

@api_view(methods=("GET",), module="tasks", level="read")
def access_requests_inbox(request):
    return access_requests.inbox(request)


@api_view(methods=("GET",), module="tasks", level="read")
def department_access_history(request, department_id: int):
    return access_requests.department_history(department_id, request, request.GET)
