"""HTTP-вьюхи домена hr — ``/api/hr/v1/{departments,positions}/*``.

Порт services/hr/app/api/v1/{departments,positions}.py. Вьюхи тонкие:
аутентификация, парсинг, коды ответа. Логика — в apps/hr/services/
{department,position}_service.py.

Один URL с разными методами обслуживается маленьким диспетчером по
``request.method`` (``api_view`` связывает один набор методов и одно тело
запроса с одной функцией) — тот же приём, что в apps/cms/views.py.

Авторизация positions (решение контроллера, docs/plans/2026-07-20-hr-domain.md):
``get_current_user`` исходника (обычный вошедший пользователь) → ``auth="jwt"``
на чтениях; ``require_hr_write`` исходника (``current_user.is_elevated`` —
admin/staff/superuser, «coarse/transitional» по комментарию самого исходника)
→ ``api_view(..., auth="jwt", admin=True)`` на записях: это РОВНО тот же
предикат (``htqweb.authn.rbac.require_admin`` читает ``token.is_elevated``).
"""
from __future__ import annotations

import json

from django.http import HttpResponse, JsonResponse
from pydantic import ValidationError

from htqweb.http import api_view, json_error

from . import schemas
from .permissions import LEVEL_PRESETS
from .services import department_service as svc
from .services import position_service as pos_svc


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


# ═══════════════════════════════════════════════════════════════════════════
#  /positions/* — порт services/hr/app/api/v1/positions.py
# ═══════════════════════════════════════════════════════════════════════════
#
# Статический каталог — отдаётся UI, чтобы админы могли собрать матрицу прав
# не хардкодя строки во фронте. Ключи авторитетны и проверяются в
# app.auth.hr_access исходника (сюда ещё не перенесён — см. employees);
# hr_level — пресет, который заполняет набор ключей. Дословный порт
# _PERMISSION_CATALOG из роутера исходника.
_PERMISSION_CATALOG = {
    "hr_levels": [
        {"value": "junior", "label": "Junior", "description": "Просмотр своих данных и базовых справочников"},
        {"value": "middle", "label": "Middle", "description": "Редактирование данных в рамках своего отдела"},
        {"value": "senior", "label": "Senior", "description": "Полный просмотр + создание сотрудников"},
        {"value": "lead",   "label": "Lead",   "description": "Полный доступ ко всем HR-функциям"},
    ],
    "permissions": [
        {"key": "hr.employees.view",    "label": "Просмотр сотрудников",   "description": None, "group": "Сотрудники"},
        {"key": "hr.employees.create",  "label": "Создание сотрудников",   "description": None, "group": "Сотрудники"},
        {"key": "hr.employees.edit",    "label": "Редактирование данных",  "description": None, "group": "Сотрудники"},
        {"key": "hr.employees.delete",  "label": "Удаление сотрудников",   "description": None, "group": "Сотрудники"},
        {"key": "hr.employees.transfer",  "label": "Переводы",               "description": None, "group": "Сотрудники"},
        {"key": "hr.employees.view.all", "label": "Просмотр всех отделов", "description": None, "group": "Сотрудники"},
        {"key": "hr.users.list",         "label": "Список платформенных аккаунтов", "description": None, "group": "Аккаунты"},
        {"key": "hr.users.manage",       "label": "Управление аккаунтами",          "description": None, "group": "Аккаунты"},

        {"key": "hr.departments.view",  "label": "Просмотр отделов",       "description": None, "group": "Отделы"},
        {"key": "hr.departments.edit",  "label": "Редактирование отделов", "description": None, "group": "Отделы"},

        {"key": "hr.positions.view",    "label": "Просмотр должностей",    "description": None, "group": "Должности"},
        {"key": "hr.positions.edit",    "label": "Редактирование должностей", "description": None, "group": "Должности"},

        {"key": "hr.documents.view",    "label": "Просмотр документов",    "description": None, "group": "Документы"},
        {"key": "hr.documents.manage",  "label": "Управление документами", "description": None, "group": "Документы"},

        {"key": "hr.reports.view",      "label": "Просмотр отчётности",    "description": None, "group": "Отчёты"},

        {"key": "hr.card.financial.view", "label": "Финансы — просмотр", "description": None, "group": "Карточка"},
        {"key": "hr.card.financial.edit", "label": "Финансы — изменение", "description": None, "group": "Карточка"},
        {"key": "hr.card.personal.view",  "label": "Личные данные — просмотр", "description": None, "group": "Карточка"},
        {"key": "hr.card.personal.edit",  "label": "Личные данные — изменение", "description": None, "group": "Карточка"},
        {"key": "hr.card.certs.view",     "label": "Сертификаты/СРО — просмотр", "description": None, "group": "Карточка"},
        {"key": "hr.card.certs.edit",     "label": "Сертификаты/СРО — изменение", "description": None, "group": "Карточка"},
        {"key": "hr.card.groups.view",    "label": "Образование/стаж/семья — просмотр", "description": None, "group": "Карточка"},
        {"key": "hr.card.groups.edit",    "label": "Образование/стаж/семья — изменение", "description": None, "group": "Карточка"},

        {"key": "hr.calendar.view",   "label": "Календарь — просмотр",  "description": None, "group": "Календарь"},
        {"key": "hr.calendar.manage", "label": "Календарь — управление", "description": None, "group": "Календарь"},

        {"key": "hr.staffing.view",   "label": "Штатное расписание — просмотр",  "description": None, "group": "Штатное расписание"},
        {"key": "hr.staffing.manage", "label": "Штатное расписание — управление", "description": None, "group": "Штатное расписание"},
    ],
    "level_presets": {lvl: sorted(keys) for lvl, keys in LEVEL_PRESETS.items()},
}


def _query_error(exc: ValidationError) -> JsonResponse:
    return JsonResponse({"detail": json.loads(exc.json())}, status=422)


# ── /positions/ — коллекция (литеральные роуты — ДО /{id}/) ─────────────────

@api_view(methods=("GET",), auth="jwt")
def _list_positions(request):
    try:
        query = schemas.PositionListQuery.model_validate(dict(request.GET.items()))
    except ValidationError as exc:
        return _query_error(exc)
    items, total = pos_svc.list_positions(page=query.page, limit=query.limit)
    return pos_svc.paginate(
        [pos_svc.serialize(p) for p in items], total=total, page=query.page, limit=query.limit,
    )


@api_view(methods=("POST",), auth="jwt", admin=True, body=schemas.PositionCreate, status=201)
def _create_position(request, data: schemas.PositionCreate):
    try:
        pos = pos_svc.create_position(data)
    except pos_svc.WeightTaken as exc:
        return json_error(exc.detail, 409)
    return pos_svc.serialize(pos)


def positions_collection(request):
    if request.method == "GET":
        return _list_positions(request)
    if request.method == "POST":
        return _create_position(request)
    return json_error("Method Not Allowed", 405)


# ── /positions/levels/ — пороги уровней (ДО /{id}/) ──────────────────────────

@api_view(methods=("GET",), auth="jwt")
def _list_level_thresholds(request):
    return [pos_svc.serialize_threshold(t) for t in pos_svc.list_thresholds()]


@api_view(methods=("POST",), auth="jwt", admin=True, body=schemas.LevelThresholdCreate, status=201)
def _create_level_threshold(request, data: schemas.LevelThresholdCreate):
    try:
        threshold = pos_svc.create_threshold(data, actor_user_id=request.token.user_id)
    except (pos_svc.ThresholdExists, pos_svc.ThresholdRangeOverlap) as exc:
        return json_error(exc.detail, 409)
    except pos_svc.ThresholdRangeInvalid as exc:
        return json_error(exc.detail, 422)
    return pos_svc.serialize_threshold(threshold)


def level_thresholds_collection(request):
    if request.method == "GET":
        return _list_level_thresholds(request)
    if request.method == "POST":
        return _create_level_threshold(request)
    return json_error("Method Not Allowed", 405)


@api_view(methods=("PUT",), auth="jwt", admin=True, body=schemas.LevelThresholdUpdate)
def _update_level_threshold(request, level_number: int, data: schemas.LevelThresholdUpdate):
    try:
        threshold = pos_svc.update_threshold(level_number, data, actor_user_id=request.token.user_id)
    except pos_svc.ThresholdRangeOverlap as exc:
        return json_error(exc.detail, 409)
    except pos_svc.ThresholdRangeInvalid as exc:
        return json_error(exc.detail, 422)
    return pos_svc.serialize_threshold(threshold)


@api_view(methods=("DELETE",), auth="jwt", admin=True)
def _delete_level_threshold(request, level_number: int):
    pos_svc.delete_threshold(level_number, actor_user_id=request.token.user_id)
    return HttpResponse(status=204)


def level_threshold_detail(request, level_number: int):
    if request.method == "PUT":
        return _update_level_threshold(request, level_number=level_number)
    if request.method == "DELETE":
        return _delete_level_threshold(request, level_number=level_number)
    return json_error("Method Not Allowed", 405)


# ── /positions/permissions-catalog/ ───────────────────────────────────────────

@api_view(methods=("GET",), auth="jwt")
def get_permissions_catalog(request):
    return _PERMISSION_CATALOG


# ── /positions/rebalance ──────────────────────────────────────────────────────

@api_view(methods=("POST",), auth="jwt", admin=True, body=schemas.PositionRebalanceRequest)
def rebalance_positions(request, data: schemas.PositionRebalanceRequest):
    # Http404 из rebalance_level (порог не найден) не ловим здесь нарочно —
    # api_view сам превращает его в {"detail": ...} 404 (см. htqweb/http.py).
    if data.level is not None:
        count = pos_svc.rebalance_level(data.level, actor_user_id=request.token.user_id)
        return {"levels": {data.level: count}, "total": count}
    levels = pos_svc.rebalance_all(actor_user_id=request.token.user_id)
    return {"levels": levels, "total": sum(levels.values())}


# ── /positions/{id}/ — детальный ресурс (catch-all — В КОНЦЕ) ────────────────

@api_view(methods=("GET",), auth="jwt")
def _get_position(request, id: int):
    return pos_svc.serialize(pos_svc.get_position(id))


@api_view(methods=("PUT", "PATCH"), auth="jwt", admin=True, body=schemas.PositionUpdate)
def _update_position(request, id: int, data: schemas.PositionUpdate):
    # PUT — задокументированный контракт исходника; PATCH — то, что реально
    # шлёт фронт (frontend/src/api/hr.ts::updatePosition) — тот же живой
    # 405-баг, что закрыт в departments. Регистрируем оба, строго аддитивно.
    try:
        pos = pos_svc.update_position(id, data, actor_user_id=request.token.user_id)
    except pos_svc.SystemPositionFieldsLocked as exc:
        return json_error(exc.detail, 409)
    except pos_svc.WeightTaken as exc:
        return json_error(exc.detail, 409)
    except pos_svc.WeightInvalid as exc:
        return json_error(exc.detail, 422)
    return pos_svc.serialize(pos)


@api_view(methods=("DELETE",), auth="jwt", admin=True)
def _delete_position(request, id: int):
    try:
        pos_svc.delete_position(id)
    except pos_svc.SystemPositionProtected as exc:
        return json_error(exc.detail, 409)
    return HttpResponse(status=204)


def position_detail(request, id: int):
    if request.method == "GET":
        return _get_position(request, id=id)
    if request.method in ("PUT", "PATCH"):
        return _update_position(request, id=id)
    if request.method == "DELETE":
        return _delete_position(request, id=id)
    return json_error("Method Not Allowed", 405)


# ── /positions/{id}/weight ─────────────────────────────────────────────────

@api_view(methods=("PATCH",), auth="jwt", admin=True, body=schemas.PositionWeightUpdate)
def update_position_weight(request, id: int, data: schemas.PositionWeightUpdate):
    try:
        pos = pos_svc.update_weight(id, data.weight, actor_user_id=request.token.user_id)
    except pos_svc.WeightTaken as exc:
        return json_error(exc.detail, 409)
    except pos_svc.WeightInvalid as exc:
        return json_error(exc.detail, 422)
    return pos_svc.serialize(pos)


# ── /positions/{id}/move ────────────────────────────────────────────────────

@api_view(methods=("PATCH",), auth="jwt", admin=True, body=schemas.PositionMoveRequest)
def move_position(request, id: int, data: schemas.PositionMoveRequest):
    try:
        pos = pos_svc.move_position(
            id,
            before_position_id=data.before_position_id,
            after_position_id=data.after_position_id,
            target_level=data.target_level,
            actor_user_id=request.token.user_id,
        )
    except pos_svc.MoveValidationError as exc:
        return json_error(exc.detail, 422)
    return pos_svc.serialize(pos)
