"""HTTP-вьюхи домена hr — ``/api/hr/v1/departments/*``.

Порт services/hr/app/api/v1/departments.py. Вьюхи тонкие: аутентификация,
парсинг, коды ответа. Логика — в apps/hr/services/department_service.py.

Один URL с разными методами обслуживается маленьким диспетчером по
``request.method`` (``api_view`` связывает один набор методов и одно тело
запроса с одной функцией) — тот же приём, что в apps/cms/views.py.
"""
from __future__ import annotations

from django.http import HttpResponse

from htqweb.http import api_view, json_error

from . import schemas
from .services import department_service as svc


def _wants_cascade(request) -> bool:
    return request.GET.get("cascade", "").lower() in ("1", "true", "yes")


# ── /departments/ — коллекция ───────────────────────────────────────────────

@api_view(methods=("GET",), auth="jwt")
def _list_departments(request):
    return svc.list_departments()


@api_view(methods=("POST",), auth="jwt", body=schemas.DepartmentCreate, status=201)
def _create_department(request, data: schemas.DepartmentCreate):
    try:
        dep = svc.create_department(data)
    except svc.DepartmentNotFound:
        # parent_id указывает на несуществующий отдел
        return json_error("Department not found", 404)
    return svc.serialize(dep)


def departments_collection(request):
    if request.method == "GET":
        return _list_departments(request)
    if request.method == "POST":
        return _create_department(request)
    return json_error("Method Not Allowed", 405)


# ── /departments/tree ───────────────────────────────────────────────────────

@api_view(methods=("GET",), auth="jwt")
def department_tree(request):
    return svc.get_tree()


# ── /departments/{id}/ — детальный ресурс ───────────────────────────────────

@api_view(methods=("GET",), auth="jwt")
def _get_department(request, department_id: int):
    try:
        return svc.serialize(svc.get_department(department_id))
    except svc.DepartmentNotFound:
        return json_error("Department not found", 404)


@api_view(methods=("PUT", "PATCH"), auth="jwt", body=schemas.DepartmentUpdate)
def _update_department(request, department_id: int, data: schemas.DepartmentUpdate):
    try:
        return svc.serialize(svc.update_department(department_id, data))
    except svc.DepartmentNotFound:
        return json_error("Department not found", 404)


@api_view(methods=("DELETE",), auth="jwt")
def _delete_department(request, department_id: int):
    try:
        svc.delete_department(department_id, cascade=_wants_cascade(request))
    except svc.DepartmentNotFound:
        return json_error("Department not found", 404)
    except svc.DepartmentHasDependents as exc:
        # СТРУКТУРНЫЙ detail (объект, не строка) — по нему фронт рисует
        # точное подтверждение и повторяет запрос с cascade=true.
        return json_error(exc.detail, 409)
    return HttpResponse(status=204)


def department_detail(request, department_id: int):
    if request.method == "GET":
        return _get_department(request, department_id=department_id)
    if request.method in ("PUT", "PATCH"):
        # PUT — задокументированный контракт исходника; PATCH — то, что реально
        # шлёт фронт (frontend/src/api/hr.ts::updateDepartment) и на чём сейчас
        # получает 405. Регистрируем оба: строго аддитивно, PUT не меняется.
        return _update_department(request, department_id=department_id)
    if request.method == "DELETE":
        return _delete_department(request, department_id=department_id)
    return json_error("Method Not Allowed", 405)


# ── /departments/{id}/children и /{id}/employees ────────────────────────────

@api_view(methods=("GET",), auth="jwt")
def department_children(request, department_id: int):
    try:
        return svc.get_children(department_id)
    except svc.DepartmentNotFound:
        return json_error("Department not found", 404)


@api_view(methods=("GET",), auth="jwt")
def department_employees(request, department_id: int):
    try:
        return svc.get_employees(department_id)
    except svc.DepartmentNotFound:
        return json_error("Department not found", 404)
