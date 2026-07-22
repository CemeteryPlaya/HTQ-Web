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

import datetime
import json
import os

from django.conf import settings as django_settings
from django.http import HttpResponse, JsonResponse
from pydantic import ValidationError

from htqweb.http import api_view, json_error

from apps.users import interface as users_interface

from . import access as hr_access
from . import schemas
from .permissions import (
    CALENDAR_MANAGE,
    CALENDAR_VIEW,
    CARD_GROUPS_EDIT,
    CARD_GROUPS_VIEW,
    LEVEL_PRESETS,
    STAFFING_MANAGE,
    STAFFING_VIEW,
)
from .services import audit_service
from .services import calendar_service as cal_svc
from .services import department_file_service as dept_file_svc
from .services import department_service as svc
from .services import document_service as doc_svc
from .services import employee_card_service as card_svc
from .services import employee_card_t2_service as card_t2_svc
from .services import employee_groups_service as groups_svc
from .services import employee_service as emp_svc
from .services import internal_service as internal_svc
from .services import org_service
from .services import personnel_history_service as ph_svc
from .services import pmo_service as pmo_svc
from .services import position_service as pos_svc
from .services import recruitment_service as rec_svc
from .services import share_link_service as share_link_svc
from .services import staffing_service as staffing_svc
from .services import time_service as time_svc


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
    # WeightTaken ловим явно: внутренний ребаланс может упереться в коллизию
    # веса (реально при рассинхроне weight/level у строк, вставленных мимо API
    # — сценарий ETL-миграции). Исходник в этом случае отдаёт 409 (HTTPException
    # всплывает глобально); api_view так не умеет, иначе — молчаливый 500.
    try:
        if data.level is not None:
            count = pos_svc.rebalance_level(data.level, actor_user_id=request.token.user_id)
            return {"levels": {data.level: count}, "total": count}
        levels = pos_svc.rebalance_all(actor_user_id=request.token.user_id)
        return {"levels": levels, "total": sum(levels.values())}
    except pos_svc.WeightTaken as exc:
        return json_error(exc.detail, 409)


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
    except pos_svc.WeightTaken as exc:
        # move с fallback на ребаланс уровня (_rebalance_insert) может упереться
        # в коллизию веса с должностью вне уровня — исходник отдаёт 409, а не 500.
        return json_error(exc.detail, 409)
    return pos_svc.serialize(pos)


# ═══════════════════════════════════════════════════════════════════════════
#  /employees/* — порт services/hr/app/api/v1/employees.py (14 из 16
#  эндпойнтов; 2 отложены — users/ GET+POST, ждут apps.users.interface (Р3
#  без S2S), см. растяжку в tests/test_employees_api.py). me/card и
#  {id}/card — раскрыты под-модулем employee_card (EmployeeCard/build_card).
# ═══════════════════════════════════════════════════════════════════════════
#
# Авторизация здесь — НЕ грубый api_view(admin=True) (как в positions):
# каждая вьюха аутентифицирует через ``auth="jwt"``, затем сама зовёт
# ``hr_access.resolve_hr_access(request.token)`` и проверяет ``access.can_*``,
# поднимая нужный 403 с ТОЧНЫМ detail исходника. ``HRAccessDenied`` несёт
# detail "HR access required" / "HR write access required" (require_hr_access/
# require_can_write_basic); остальные 403 ("Senior HR access required", "CO HR
# access required", "Transferring, changing position...") — inline, как в
# роутере исходника.


def _require_visible_employee(id: int, access: hr_access.HRAccess):
    """Порт ``_require_visible_employee`` роутера исходника.

    404 "Employee not found" (НЕ 403) для чужого отдела — намеренно: не
    раскрываем существование сотрудника вне своего скоупа. Оба случая
    (не существует / не виден) дают идентичный detail, поэтому объединены в
    одно исключение.
    """
    employee = emp_svc.get_employee(id)
    if not access.can_see_department(employee.department_id):
        raise emp_svc.EmployeeNotFound
    return employee


# ── /employees/hr-level/ (литеральный роут — ДО /{id}/) ──────────────────────

@api_view(methods=("GET",), auth="jwt")
def employee_hr_level(request):
    access = hr_access.resolve_hr_access(request.token)
    return {
        "level": access.level,
        "scope_department_id": access.department_id,
        "can_read_all": access.can_read_all,
        "can_write_basic": access.can_write_basic,
        "can_create_employee": access.can_create_employee,
        "can_transfer_employee": access.can_transfer_employee,
        "can_delete_employee": access.can_delete_employee,
        "can_list_user_options": access.can_list_user_options,
        "can_manage_user_options": access.can_manage_user_options,
        "permissions": sorted(access.permissions),
    }


# ── /employees/me/ (литеральный роут — ДО /{id}/) ─────────────────────────────

@api_view(methods=("GET",), auth="jwt")
def my_employee(request):
    employee = emp_svc.get_my_employee(request.token)
    if employee is None:
        return json_error("Employee profile not found", 404)
    return svc.serialize_employee(employee)


# ── /employees/users/ (литеральный роут — ДО /{id}/) ─────────────────────────
#
# Порт services/hr/app/api/v1/employees.py::list_user_options/
# create_user_option — исходник проксировал user-service (никакого S2S в
# этом монолите); здесь оба зовут apps.users.interface напрямую (Р3, без
# S2S). Форма ответа — HRUserOption исходника: {id, full_name, email,
# first_name, last_name} — username/patronymic, которые interface тоже
# отдаёт, здесь намеренно отброшены (исходник тоже их не выставляет в
# HRUserOption, хотя create_user_option пытается их туда положить —
# pydantic молча игнорирует лишние поля конструктора).

def _serialize_user_option(user: dict) -> dict:
    return {
        "id": user["id"],
        "full_name": user["full_name"],
        "email": user["email"],
        "first_name": user.get("first_name", ""),
        "last_name": user.get("last_name", ""),
    }


@api_view(methods=("GET",), auth="jwt")
def _list_user_options(request):
    try:
        access = hr_access.require_hr_access(hr_access.resolve_hr_access(request.token))
    except hr_access.HRAccessDenied as exc:
        return json_error(exc.detail, 403)
    if not access.can_list_user_options:
        return json_error("Senior HR access required", 403)

    users = users_interface.list_users_brief()
    return [_serialize_user_option(u) for u in users]


@api_view(methods=("POST",), auth="jwt", body=schemas.HRUserCreateRequest, status=201)
def _create_user_option(request, data: schemas.HRUserCreateRequest):
    try:
        access = hr_access.require_hr_access(hr_access.resolve_hr_access(request.token))
    except hr_access.HRAccessDenied as exc:
        return json_error(exc.detail, 403)
    if not access.can_manage_user_options:
        return json_error("CO HR access required", 403)

    if not data.email or "@" not in data.email:
        return json_error("Email обязателен и должен быть валидным", 422)

    try:
        user = users_interface.create_user(
            email=data.email,
            first_name=data.first_name,
            last_name=data.last_name,
            patronymic=data.patronymic,
        )
    except (users_interface.DuplicateEmail, users_interface.DuplicateUsername):
        return json_error("Пользователь с такими данными уже существует", 409)
    return _serialize_user_option(user)


def employees_users_collection(request):
    if request.method == "GET":
        return _list_user_options(request)
    if request.method == "POST":
        return _create_user_option(request)
    return json_error("Method Not Allowed", 405)


# ── /employees/ — коллекция ───────────────────────────────────────────────

@api_view(methods=("GET",), auth="jwt")
def _list_employees(request):
    try:
        query = schemas.EmployeeListQuery.model_validate(dict(request.GET.items()))
    except ValidationError as exc:
        return _query_error(exc)

    try:
        access = hr_access.require_hr_access(hr_access.resolve_hr_access(request.token))
    except hr_access.HRAccessDenied as exc:
        return json_error(exc.detail, 403)

    effective_department_id = query.department_id
    if not access.can_read_all:
        if access.department_id is None or (
            query.department_id is not None and query.department_id != access.department_id
        ):
            return {"items": [], "total": 0, "page": query.page, "pages": 0, "limit": query.limit}
        effective_department_id = access.department_id

    items, total = emp_svc.list_employees(
        department_id=effective_department_id,
        status=query.status,
        search=query.search,
        page=query.page,
        limit=query.limit,
    )
    pages = (total + query.limit - 1) // query.limit
    return {
        "items": [svc.serialize_employee(e) for e in items],
        "total": total,
        "page": query.page,
        "pages": pages,
        "limit": query.limit,
    }


@api_view(methods=("POST",), auth="jwt", body=schemas.EmployeeCreate, status=201)
def _create_employee(request, data: schemas.EmployeeCreate):
    try:
        access = hr_access.require_hr_access(hr_access.resolve_hr_access(request.token))
    except hr_access.HRAccessDenied as exc:
        return json_error(exc.detail, 403)
    if not access.can_create_employee:
        return json_error("Senior HR access required", 403)

    try:
        employee = emp_svc.create_employee(data, changed_by_id=request.token.user_id)
    except emp_svc.DepartmentNotFound:
        return json_error("Department not found", 422)
    except emp_svc.PositionNotFound:
        return json_error("Position not found", 422)
    except emp_svc.EmailAlreadyInUse:
        return json_error("Email already in use", 409)
    return svc.serialize_employee(employee)


def employees_collection(request):
    if request.method == "GET":
        return _list_employees(request)
    if request.method == "POST":
        return _create_employee(request)
    return json_error("Method Not Allowed", 405)


# ── /employees/{id}/ — детальный ресурс ────────────────────────────────────

@api_view(methods=("GET",), auth="jwt")
def _get_employee(request, id: int):
    try:
        access = hr_access.require_hr_access(hr_access.resolve_hr_access(request.token))
    except hr_access.HRAccessDenied as exc:
        return json_error(exc.detail, 403)
    try:
        employee = _require_visible_employee(id, access)
    except emp_svc.EmployeeNotFound:
        return json_error("Employee not found", 404)
    return svc.serialize_employee(employee)


@api_view(methods=("PUT", "PATCH"), auth="jwt", body=schemas.EmployeeUpdate)
def _update_employee(request, id: int, data: schemas.EmployeeUpdate):
    # PUT — задокументированный контракт исходника; PATCH регистрируем тоже
    # (аддитивно), как и в departments/positions.
    try:
        access = hr_access.require_can_write_basic(hr_access.resolve_hr_access(request.token))
    except hr_access.HRAccessDenied as exc:
        return json_error(exc.detail, 403)
    try:
        _require_visible_employee(id, access)
    except emp_svc.EmployeeNotFound:
        return json_error("Employee not found", 404)

    if not access.can_transfer_employee and (
        data.department_id is not None
        or data.position_id is not None
        or data.termination_date is not None
        or data.status in {"terminated", "suspended", "rejected"}
    ):
        return json_error(
            "Transferring, changing position, or terminating requires the transfer permission",
            403,
        )

    try:
        employee = emp_svc.update_employee(id, data, changed_by_id=request.token.user_id)
    except emp_svc.DepartmentNotFound:
        return json_error("Department not found", 422)
    except emp_svc.PositionNotFound:
        return json_error("Position not found", 422)
    except emp_svc.EmailAlreadyInUse:
        return json_error("Email already in use", 409)
    return svc.serialize_employee(employee)


@api_view(methods=("DELETE",), auth="jwt")
def _delete_employee(request, id: int):
    try:
        access = hr_access.require_hr_access(hr_access.resolve_hr_access(request.token))
    except hr_access.HRAccessDenied as exc:
        return json_error(exc.detail, 403)
    if not access.can_delete_employee:
        return json_error("CO HR access required", 403)
    try:
        _require_visible_employee(id, access)
    except emp_svc.EmployeeNotFound:
        return json_error("Employee not found", 404)
    emp_svc.delete_employee(id, changed_by_id=request.token.user_id)
    return HttpResponse(status=204)


def employee_detail(request, id: int):
    if request.method == "GET":
        return _get_employee(request, id=id)
    if request.method in ("PUT", "PATCH"):
        return _update_employee(request, id=id)
    if request.method == "DELETE":
        return _delete_employee(request, id=id)
    return json_error("Method Not Allowed", 405)


# ── /employees/{id}/transfer ────────────────────────────────────────────────

@api_view(methods=("POST",), auth="jwt", body=schemas.EmployeeTransfer)
def transfer_employee(request, id: int, data: schemas.EmployeeTransfer):
    try:
        access = hr_access.require_hr_access(hr_access.resolve_hr_access(request.token))
    except hr_access.HRAccessDenied as exc:
        return json_error(exc.detail, 403)
    if not access.can_transfer_employee:
        return json_error("Senior HR access required", 403)
    try:
        _require_visible_employee(id, access)
    except emp_svc.EmployeeNotFound:
        return json_error("Employee not found", 404)

    try:
        employee = emp_svc.transfer_employee(id, data, changed_by_id=request.token.user_id)
    except emp_svc.DepartmentNotFound:
        return json_error("Department not found", 422)
    except emp_svc.PositionNotFound:
        return json_error("Position not found", 422)
    return svc.serialize_employee(employee)


# ── /employees/{id}/history ─────────────────────────────────────────────────

@api_view(methods=("GET",), auth="jwt")
def employee_history(request, id: int):
    try:
        access = hr_access.require_hr_access(hr_access.resolve_hr_access(request.token))
    except hr_access.HRAccessDenied as exc:
        return json_error(exc.detail, 403)
    try:
        _require_visible_employee(id, access)
    except emp_svc.EmployeeNotFound:
        return json_error("Employee not found", 404)
    return emp_svc.get_history(id)


# ── /employees/{id}/documents ────────────────────────────────────────────────
#
# Порт employees.py::employee_documents (исходник, hr-docs под-модуль): та же
# пара require_hr_access + _require_visible_employee, что и history выше
# (буквально идентичный auth-пролог исходника: ``require_hr_access(await
# resolve_hr_access(db, current_user))`` + ``_require_visible_employee``).
# Раскрыт после переноса модели Document (apps/hr/services/document_service.py)
# — растяжка test_documents_endpoint_todo_is_tracked в test_employees_api.py
# снята.

@api_view(methods=("GET",), auth="jwt")
def employee_documents(request, id: int):
    try:
        access = hr_access.require_hr_access(hr_access.resolve_hr_access(request.token))
    except hr_access.HRAccessDenied as exc:
        return json_error(exc.detail, 403)
    try:
        _require_visible_employee(id, access)
    except emp_svc.EmployeeNotFound:
        return json_error("Employee not found", 404)
    return doc_svc.list_for_employee(id)


# ── /employees/me/pmos, /employees/{id}/pmos ────────────────────────────────
#
# Порт employees.py::my_pmos/employee_pmos исходника (растяжки
# test_pmo_endpoints_todo_is_tracked в test_employees_api.py сняты теперь,
# когда модель PMO появилась под-модулем pmo). Обе зовут
# ``PMOService.get_employee_pmos`` исходника — здесь pmo_svc.get_employee_pmos
# (см. apps/hr/services/pmo_service.py). Auth — идентична соседям: /me/pmos
# резолвит СВОЙ Employee (как my_employee выше, 404 "Employee profile not
# found" при отсутствии профиля); /{id}/pmos — require_hr_access +
# _require_visible_employee (как history/documents выше).

@api_view(methods=("GET",), auth="jwt")
def my_pmos(request):
    employee = emp_svc.get_my_employee(request.token)
    if employee is None:
        return json_error("Employee profile not found", 404)
    return pmo_svc.get_employee_pmos(employee.id)


@api_view(methods=("GET",), auth="jwt")
def employee_pmos(request, id: int):
    try:
        access = hr_access.require_hr_access(hr_access.resolve_hr_access(request.token))
    except hr_access.HRAccessDenied as exc:
        return json_error(exc.detail, 403)
    try:
        _require_visible_employee(id, access)
    except emp_svc.EmployeeNotFound:
        return json_error("Employee not found", 404)
    return pmo_svc.get_employee_pmos(id)


# ── /employees/me/card, /employees/{id}/card ────────────────────────────────
#
# Порт employees.py::my_employee_card/employee_card исходника — РАСКРЫТЫ этим
# под-модулем (модель EmployeeCard появилась, employee_card_service.build_card
# перенесён). ``/me/card`` — БЕЗ require_hr_access, буквально как исходник
# (``access = await resolve_hr_access(db, current_user)`` — НЕ обёрнуто в
# require_hr_access, в отличие от /{id}/card ниже и от /me/pmos выше, который
# access вообще не резолвит): любой со своим Employee-профилем видит СВОЮ
# карточку целиком (email/phone/manager/subordinates/pmos — всегда), а Т-2
# секции внутри неё (``card["t2"]``) гейтятся ПОЛЕВЫМ RBAC card_t2_svc —
# сотрудник без единого hr.card.*.view ключа получит пустой ``t2: {}``, но не
# 403 на сам эндпойнт. ``/{id}/card`` — ТА ЖЕ пара require_hr_access +
# _require_visible_employee, что history/documents/pmos выше (403 "HR access
# required" при полном отсутствии HR-доступа, 404 "Employee not found" за
# несуществующего/невидимого — приватность, не различаем случаи).

@api_view(methods=("GET",), auth="jwt")
def my_employee_card(request):
    employee = emp_svc.get_my_employee(request.token)
    if employee is None:
        return json_error("Employee profile not found", 404)
    access = hr_access.resolve_hr_access(request.token)
    return card_svc.build_card(employee.id, mode="full", access=access)


@api_view(methods=("GET",), auth="jwt")
def employee_card(request, id: int):
    try:
        access = hr_access.require_hr_access(hr_access.resolve_hr_access(request.token))
    except hr_access.HRAccessDenied as exc:
        return json_error(exc.detail, 403)
    try:
        _require_visible_employee(id, access)
    except emp_svc.EmployeeNotFound:
        return json_error("Employee not found", 404)
    return card_svc.build_card(id, mode="full", access=access)


# ═══════════════════════════════════════════════════════════════════════════
#  /org/* — порт services/hr/app/api/v1/org.py (6 эндпойнтов)
# ═══════════════════════════════════════════════════════════════════════════
#
# Авторизация (решение контроллера, docs/plans/2026-07-20-hr-domain.md,
# под-модуль org): reads = ``get_current_user`` исходника -> ``auth="jwt"``;
# writes = ``require_hr_write`` исходника (``current_user.is_elevated``) ->
# ``api_view(auth="jwt", admin=True)`` — ровно тот же предикат, что у
# positions/*. Тонкий ``hr_access`` (как в employees) здесь НЕ нужен —
# исходный org.py тоже использует грубую пару get_current_user/require_hr_write,
# а не HRAccess.


@api_view(methods=("GET",), auth="jwt")
def org_tree(request):
    try:
        query = schemas.OrgTreeQuery.model_validate(dict(request.GET.items()))
    except ValidationError as exc:
        return _query_error(exc)
    return org_service.get_org_tree(
        root_id=query.root_id, depth=query.depth, mode=query.mode, lang=query.lang,
    )


# ── /org/subordination-matrix ────────────────────────────────────────────────

@api_view(methods=("GET",), auth="jwt")
def org_subordination_matrix(request):
    try:
        query = schemas.OrgMatrixQuery.model_validate(dict(request.GET.items()))
    except ValidationError as exc:
        return _query_error(exc)
    return org_service.get_subordination_matrix(unit_id=query.unit_id)


# ── /org/relations — CRUD ─────────────────────────────────────────────────────

@api_view(methods=("POST",), auth="jwt", admin=True, body=schemas.RelationCreate, status=201)
def add_reporting_relation(request, data: schemas.RelationCreate):
    try:
        rel = org_service.add_relation(
            superior_id=data.superior_position_id,
            subordinate_id=data.subordinate_position_id,
            relation_type=data.relation_type,
            effective_from=data.effective_from,
            effective_to=data.effective_to,
        )
    except org_service.RelationSelfReferential as exc:
        return json_error(exc.detail, 422)
    except org_service.RelationDuplicate as exc:
        return json_error(exc.detail, 409)
    return org_service.serialize_relation(rel)


@api_view(methods=("DELETE",), auth="jwt", admin=True)
def remove_reporting_relation(request, relation_id: int):
    try:
        org_service.remove_relation(relation_id)
    except org_service.RelationNotFound as exc:
        return json_error(exc.detail, 404)
    return HttpResponse(status=204)


# ── /org/settings/deletion-strategy ────────────────────────────────────────────

@api_view(methods=("GET",), auth="jwt")
def _get_deletion_strategy(request):
    return {"deletion_strategy": org_service.get_deletion_strategy()}


@api_view(methods=("PUT",), auth="jwt", admin=True, body=schemas.OrgSettingUpdate)
def _set_deletion_strategy(request, data: schemas.OrgSettingUpdate):
    org_service.set_deletion_strategy(data.deletion_strategy)
    return {"deletion_strategy": data.deletion_strategy}


def org_deletion_strategy(request):
    if request.method == "GET":
        return _get_deletion_strategy(request)
    if request.method == "PUT":
        return _set_deletion_strategy(request)
    return json_error("Method Not Allowed", 405)


# ═══════════════════════════════════════════════════════════════════════════
#  /vacancies/* + /applications/* — порт services/hr/app/api/v1/{vacancies,
#  applications}.py (13 эндпойнтов: vacancies 6 + applications 7)
# ═══════════════════════════════════════════════════════════════════════════
#
# Авторизация — БУКВАЛЬНО как в исходнике: recruiting-роутеры (в отличие от
# positions/org) используют ТОЛЬКО ``get_current_user`` — ни один эндпойнт,
# включая POST/PUT/DELETE, не зовёт ``require_hr_write``. Это странность
# исходника (см. докстринг apps/hr/services/recruitment_service.py), не баг
# порта: ВСЕ 13 эндпойнтов ниже — ``api_view(auth="jwt")`` без ``admin=True``.


# ── /vacancies/ — коллекция ─────────────────────────────────────────────────

@api_view(methods=("GET",), auth="jwt")
def _list_vacancies(request):
    try:
        query = schemas.VacancyListQuery.model_validate(dict(request.GET.items()))
    except ValidationError as exc:
        return _query_error(exc)
    items, total = rec_svc.list_vacancies(
        status=query.status, department_id=query.department_id, page=query.page, limit=query.limit,
    )
    return rec_svc.paginate(
        [rec_svc.serialize_vacancy(v) for v in items], total=total, page=query.page, limit=query.limit,
    )


@api_view(methods=("POST",), auth="jwt", body=schemas.VacancyCreate, status=201)
def _create_vacancy(request, data: schemas.VacancyCreate):
    return rec_svc.serialize_vacancy(rec_svc.create_vacancy(data))


def vacancies_collection(request):
    if request.method == "GET":
        return _list_vacancies(request)
    if request.method == "POST":
        return _create_vacancy(request)
    return json_error("Method Not Allowed", 405)


# ── /vacancies/{id}/ — детальный ресурс ─────────────────────────────────────

@api_view(methods=("GET",), auth="jwt")
def _get_vacancy(request, id: int):
    try:
        return rec_svc.serialize_vacancy(rec_svc.get_vacancy(id))
    except rec_svc.VacancyNotFound:
        return json_error("Vacancy not found", 404)


@api_view(methods=("PUT", "PATCH"), auth="jwt", body=schemas.VacancyUpdate)
def _update_vacancy(request, id: int, data: schemas.VacancyUpdate):
    # PUT — задокументированный контракт исходника; PATCH регистрируем тоже
    # (аддитивно), как и в departments/positions/employees.
    try:
        return rec_svc.serialize_vacancy(rec_svc.update_vacancy(id, data))
    except rec_svc.VacancyNotFound:
        return json_error("Vacancy not found", 404)


@api_view(methods=("DELETE",), auth="jwt")
def _close_vacancy(request, id: int):
    # DELETE в исходнике — НЕ физическое удаление: close_vacancy помечает
    # status="closed" + closed_at=today и оставляет строку (контракт, не баг).
    try:
        rec_svc.close_vacancy(id)
    except rec_svc.VacancyNotFound:
        return json_error("Vacancy not found", 404)
    return HttpResponse(status=204)


def vacancy_detail(request, id: int):
    if request.method == "GET":
        return _get_vacancy(request, id=id)
    if request.method in ("PUT", "PATCH"):
        return _update_vacancy(request, id=id)
    if request.method == "DELETE":
        return _close_vacancy(request, id=id)
    return json_error("Method Not Allowed", 405)


# ── /vacancies/{id}/applications ────────────────────────────────────────────

@api_view(methods=("GET",), auth="jwt")
def vacancy_applications(request, id: int):
    try:
        apps = rec_svc.get_vacancy_applications(id)
    except rec_svc.VacancyNotFound:
        return json_error("Vacancy not found", 404)
    return [rec_svc.serialize_application(a) for a in apps]


# ── /applications/ — коллекция ──────────────────────────────────────────────

@api_view(methods=("GET",), auth="jwt")
def _list_applications(request):
    try:
        query = schemas.ApplicationListQuery.model_validate(dict(request.GET.items()))
    except ValidationError as exc:
        return _query_error(exc)
    items, total = rec_svc.list_applications(page=query.page, limit=query.limit)
    return rec_svc.paginate(
        [rec_svc.serialize_application(a) for a in items], total=total, page=query.page, limit=query.limit,
    )


@api_view(methods=("POST",), auth="jwt", body=schemas.ApplicationCreate, status=201)
def _create_application(request, data: schemas.ApplicationCreate):
    try:
        return rec_svc.serialize_application(rec_svc.create_application(data))
    except rec_svc.VacancyNotFound:
        # create_application проверяет существование вакансии ДО создания
        # отклика — 404 "Vacancy not found", а НЕ 422 (буквальный порт).
        return json_error("Vacancy not found", 404)


def applications_collection(request):
    if request.method == "GET":
        return _list_applications(request)
    if request.method == "POST":
        return _create_application(request)
    return json_error("Method Not Allowed", 405)


# ── /applications/archive/ (литеральный роут — ДО /{id}/) ──────────────────

@api_view(methods=("GET",), auth="jwt")
def applications_archive(request):
    return rec_svc.archive()


# ── /applications/{id}/ — детальный ресурс ──────────────────────────────────

@api_view(methods=("GET",), auth="jwt")
def _get_application(request, id: int):
    try:
        return rec_svc.serialize_application(rec_svc.get_application(id))
    except rec_svc.ApplicationNotFound:
        return json_error("Application not found", 404)


@api_view(methods=("PUT", "PATCH"), auth="jwt", body=schemas.ApplicationUpdate)
def _update_application(request, id: int, data: schemas.ApplicationUpdate):
    try:
        return rec_svc.serialize_application(rec_svc.update_application(id, data))
    except rec_svc.ApplicationNotFound:
        return json_error("Application not found", 404)


@api_view(methods=("DELETE",), auth="jwt")
def _delete_application(request, id: int):
    try:
        rec_svc.delete_application(id)
    except rec_svc.ApplicationNotFound:
        return json_error("Application not found", 404)
    return HttpResponse(status=204)


def application_detail(request, id: int):
    if request.method == "GET":
        return _get_application(request, id=id)
    if request.method in ("PUT", "PATCH"):
        return _update_application(request, id=id)
    if request.method == "DELETE":
        return _delete_application(request, id=id)
    return json_error("Method Not Allowed", 405)


# ── /applications/{id}/status ────────────────────────────────────────────────

@api_view(methods=("POST",), auth="jwt", body=schemas.ApplicationStatusChange)
def change_application_status(request, id: int, data: schemas.ApplicationStatusChange):
    try:
        return rec_svc.serialize_application(rec_svc.change_status(id, data))
    except rec_svc.ApplicationNotFound:
        return json_error("Application not found", 404)


# ═══════════════════════════════════════════════════════════════════════════
#  /time-tracking/* — порт services/hr/app/api/v1/time.py (8 эндпойнтов)
# ═══════════════════════════════════════════════════════════════════════════
#
# Авторизация — БУКВАЛЬНО как в исходнике: ВСЕ 8 эндпойнтов, включая
# POST/PUT/DELETE, используют ТОЛЬКО get_current_user (обычный jwt) — ни один
# не зовёт require_hr_write. Странность исходника (тот же паттерн, что и
# recruiting — см. комментарий там), не баг порта: любой залогиненный
# пользователь может создавать/менять/удалять чужие тайм-энтри.
# api_view(auth="jwt") без admin=True на всех 8.
#
# Фронт (frontend/src/api/hr.ts) шлёт POST на голый ``time-tracking/`` (не
# ``time-tracking/entries/``) и PATCH/DELETE на ``time-tracking/{id}/`` (без
# ``entries/``), плюс ``time-tracking/{id}/approve|reject`` — ни один из этих
# путей не определён исходником (нет в app/api/v1/time.py, нет в API.md).
# Вне контракта исходника — НЕ регистрируем (см. отчёт, открытый вопрос).
# Регистрируем ровно 8 эндпойнтов исходника + PATCH аддитивно на
# entries/{id}/ рядом с PUT (тот же приём "защитно, по конвенции", что и в
# остальных под-модулях этой аппки).

@api_view(methods=("GET",), auth="jwt")
def _list_time_entries(request):
    try:
        query = schemas.TimeEntryListQuery.model_validate(dict(request.GET.items()))
    except ValidationError as exc:
        return _query_error(exc)
    items, total = time_svc.list_entries(page=query.page, limit=query.limit)
    pages = (total + query.limit - 1) // query.limit
    return {
        "items": [time_svc.serialize(e) for e in items],
        "total": total, "page": query.page, "pages": pages, "limit": query.limit,
    }


def time_tracking_root(request):
    """``GET /time-tracking/`` — алиас /entries/ (порт list_root исходника:
    "The HR Time Tracking page hits the prefix root directly"). Только GET —
    исходник не регистрирует POST на корне."""
    if request.method == "GET":
        return _list_time_entries(request)
    return json_error("Method Not Allowed", 405)


@api_view(methods=("POST",), auth="jwt", body=schemas.TimeEntryCreate, status=201)
def _create_time_entry(request, data: schemas.TimeEntryCreate):
    # Странность исходника (контракт, не баг): ни create_entry, ни
    # update_entry не проверяют коллизию UniqueConstraint(employee, date,
    # start_time) заранее — дубликат роняет IntegrityError необработанным
    # (ни сервисом, ни роутером исходника), поэтому FastAPI отдаёт 500;
    # здесь — то же самое через общий except Exception в htqweb.http.api_view.
    return time_svc.serialize(time_svc.create_entry(data))


def time_entries_collection(request):
    if request.method == "GET":
        return _list_time_entries(request)
    if request.method == "POST":
        return _create_time_entry(request)
    return json_error("Method Not Allowed", 405)


@api_view(methods=("PUT", "PATCH"), auth="jwt", body=schemas.TimeEntryUpdate)
def _update_time_entry(request, id: int, data: schemas.TimeEntryUpdate):
    # PUT — задокументированный контракт исходника; PATCH регистрируем тоже
    # (аддитивно), как и во всех остальных под-модулях этой аппки.
    try:
        return time_svc.serialize(time_svc.update_entry(id, data))
    except time_svc.TimeEntryNotFound:
        return json_error("Time entry not found", 404)


@api_view(methods=("DELETE",), auth="jwt")
def _delete_time_entry(request, id: int):
    try:
        time_svc.delete_entry(id)
    except time_svc.TimeEntryNotFound:
        return json_error("Time entry not found", 404)
    return HttpResponse(status=204)


def time_entry_detail(request, id: int):
    if request.method in ("PUT", "PATCH"):
        return _update_time_entry(request, id=id)
    if request.method == "DELETE":
        return _delete_time_entry(request, id=id)
    return json_error("Method Not Allowed", 405)


@api_view(methods=("GET",), auth="jwt")
def time_daily_report(request):
    try:
        query = schemas.TimeDailyReportQuery.model_validate(dict(request.GET.items()))
    except ValidationError as exc:
        return _query_error(exc)
    day = query.report_date or datetime.date.today()
    return time_svc.daily_report(query.employee_id, day)


@api_view(methods=("GET",), auth="jwt")
def time_weekly_report(request):
    try:
        query = schemas.TimeWeeklyReportQuery.model_validate(dict(request.GET.items()))
    except ValidationError as exc:
        return _query_error(exc)
    return time_svc.weekly_report(query.employee_id, query.week_start)


@api_view(methods=("GET",), auth="jwt")
def time_monthly_report(request):
    try:
        query = schemas.TimeMonthlyReportQuery.model_validate(dict(request.GET.items()))
    except ValidationError as exc:
        return _query_error(exc)
    return time_svc.monthly_report(query.employee_id, query.year, query.month)


# ═══════════════════════════════════════════════════════════════════════════
#  /staffing/* — порт services/hr/app/api/v1/staffing.py (6 эндпойнтов)
# ═══════════════════════════════════════════════════════════════════════════
#
# Авторизация — НЕ hr_access.require_hr_access/require_can_write_basic
# (грубые ворота employees) и НЕ api_view(admin=True) (positions/org):
# исходник гейтит fine-grained PERMISSION-KEY через module-level
# ``_VIEW = require_permission("hr.staffing.view")``/``_MANAGE =
# require_permission("hr.staffing.manage")`` (app/auth/hr_access.py::
# require_permission) — 403 detail — ТОЧНАЯ строка f"Missing permission:
# {key}", отличная от HRAccessDenied ("HR access required"/"HR write access
# required"). Порт: _require_permission(request, key) ниже воспроизводит это
# буквально через hr_access.resolve_hr_access(request.token).has(key).

def _require_permission(request, key: str):
    """None, err — err — готовый json_error(403) если ключа нет у вызывающего."""
    access = hr_access.resolve_hr_access(request.token)
    if not access.has(key):
        return None, json_error(f"Missing permission: {key}", 403)
    return access, None


@api_view(methods=("GET",), auth="jwt")
def staffing_occupancy(request):
    _, err = _require_permission(request, STAFFING_VIEW)
    if err:
        return err
    return staffing_svc.occupancy()


@api_view(methods=("GET",), auth="jwt")
def staffing_summary(request):
    _, err = _require_permission(request, STAFFING_VIEW)
    if err:
        return err
    return staffing_svc.payroll_summary()


@api_view(methods=("GET",), auth="jwt")
def _list_staffing_lines(request):
    _, err = _require_permission(request, STAFFING_VIEW)
    if err:
        return err
    try:
        query = schemas.StaffingListQuery.model_validate(dict(request.GET.items()))
    except ValidationError as exc:
        return _query_error(exc)
    return [staffing_svc.line_out(line) for line in staffing_svc.list_lines(query.department_id)]


@api_view(methods=("POST",), auth="jwt", body=schemas.StaffingLineIn, status=201)
def _create_staffing_line(request, data: schemas.StaffingLineIn):
    _, err = _require_permission(request, STAFFING_MANAGE)
    if err:
        return err
    try:
        line = staffing_svc.create_line(data.model_dump())
    except staffing_svc.StaffingRefNotFound as exc:
        return json_error(exc.detail, 422)
    return staffing_svc.line_out(line)


def staffing_lines_collection(request):
    if request.method == "GET":
        return _list_staffing_lines(request)
    if request.method == "POST":
        return _create_staffing_line(request)
    return json_error("Method Not Allowed", 405)


@api_view(methods=("PUT",), auth="jwt", body=schemas.StaffingLineIn)
def _update_staffing_line(request, line_id: int, data: schemas.StaffingLineIn):
    # Исходник регистрирует ТОЛЬКО PUT здесь (нет отдельной Update-схемы —
    # StaffingLineIn используется и для create, и для update, тело всегда
    # ПОЛНОЕ). Фронт (frontend/src/api/hr.ts) не шлёт PATCH на /staffing/{id}
    # — в отличие от departments/positions/employees/vacancies/applications/
    # time-tracking, здесь НЕТ живого мисматча, поэтому PATCH не регистрируем.
    _, err = _require_permission(request, STAFFING_MANAGE)
    if err:
        return err
    try:
        line = staffing_svc.update_line(line_id, data.model_dump())
    except staffing_svc.StaffingLineNotFound:
        return json_error("Staffing line not found", 404)
    except staffing_svc.StaffingRefNotFound as exc:
        return json_error(exc.detail, 422)
    return staffing_svc.line_out(line)


@api_view(methods=("DELETE",), auth="jwt")
def _delete_staffing_line(request, line_id: int):
    _, err = _require_permission(request, STAFFING_MANAGE)
    if err:
        return err
    try:
        staffing_svc.delete_line(line_id)
    except staffing_svc.StaffingLineNotFound:
        return json_error("Staffing line not found", 404)
    return HttpResponse(status=204)


def staffing_line_detail(request, line_id: int):
    if request.method == "PUT":
        return _update_staffing_line(request, line_id=line_id)
    if request.method == "DELETE":
        return _delete_staffing_line(request, line_id=line_id)
    return json_error("Method Not Allowed", 405)


# ═══════════════════════════════════════════════════════════════════════════
#  /personnel-history/* — порт services/hr/app/api/v1/personnel_history.py
#  (4 эндпойнта)
# ═══════════════════════════════════════════════════════════════════════════
#
# Авторизация (решение контроллера): reads = get_current_user исходника ->
# auth="jwt"; writes = require_hr_write исходника (is_elevated) ->
# api_view(admin=True) — ровно та же пара, что у departments/positions/org.
# Фронт (frontend/src/pages/hr/HRHistory.tsx) шлёт PUT на update — совпадает
# с исходником буквально, PATCH не регистрируем (нет живого мисматча).

@api_view(methods=("GET",), auth="jwt")
def _list_personnel_history(request):
    return [ph_svc.serialize(ph) for ph in ph_svc.list_history()]


@api_view(methods=("POST",), auth="jwt", admin=True, body=schemas.PersonnelHistoryIn, status=201)
def _create_personnel_history(request, data: schemas.PersonnelHistoryIn):
    try:
        ph = ph_svc.create_history(data, created_by=request.token.user_id)
    except ph_svc.InvalidEventType as exc:
        # 400, НЕ 422 — буквальный порт (роутер исходника поднимает
        # HTTPException(status_code=400, ...) для event_type вне EVENT_TYPES).
        return json_error(exc.detail, 400)
    return ph_svc.serialize(ph)


def personnel_history_collection(request):
    if request.method == "GET":
        return _list_personnel_history(request)
    if request.method == "POST":
        return _create_personnel_history(request)
    return json_error("Method Not Allowed", 405)


@api_view(methods=("PUT",), auth="jwt", admin=True, body=schemas.PersonnelHistoryIn)
def _update_personnel_history(request, id: int, data: schemas.PersonnelHistoryIn):
    try:
        ph = ph_svc.update_history(id, data)
    except ph_svc.PersonnelHistoryNotFound:
        return json_error("PersonnelHistory not found", 404)
    except ph_svc.InvalidEventType as exc:
        return json_error(exc.detail, 400)
    return ph_svc.serialize(ph)


@api_view(methods=("DELETE",), auth="jwt", admin=True)
def _delete_personnel_history(request, id: int):
    try:
        ph_svc.delete_history(id)
    except ph_svc.PersonnelHistoryNotFound:
        return json_error("PersonnelHistory not found", 404)
    return HttpResponse(status=204)


def personnel_history_detail(request, id: int):
    if request.method == "PUT":
        return _update_personnel_history(request, id=id)
    if request.method == "DELETE":
        return _delete_personnel_history(request, id=id)
    return json_error("Method Not Allowed", 405)


# ═══════════════════════════════════════════════════════════════════════════
#  /calendar/* + /employees/{id}/calendar* — порт services/hr/app/api/v1/
#  calendar.py (14 + 6 = 20 эндпойнтов: 14 в router "/calendar", 6 в
#  employee_calendar_router "/employees", оба смонтированы под /api/hr/v1/).
# ═══════════════════════════════════════════════════════════════════════════
#
# Авторизация /calendar/*, brief-решение (docs/plans/2026-07-20-hr-domain.md):
# ТА ЖЕ схема, что у staffing выше — module-level _VIEW/_MANAGE исходника
# (require_permission("hr.calendar.view")/require_permission(
# "hr.calendar.manage")) -> переиспользуем _require_permission(request, key)
# уже определённую для staffing (буквально та же fine-grained проверка,
# app/auth/hr_access.py::require_permission).
#
# Авторизация /employees/{id}/calendar* — ОТДЕЛЬНАЯ схема исходника
# (_visible() роутера calendar.py): СНАЧАЛА require_hr_access (403 "HR access
# required" при полном отсутствии HR-доступа) -> ЗАТЕМ EmployeeService.
# get_employee + can_see_department (404 "Employee not found" и за
# несуществующего, и за невидимого сотрудника) -> ТОЛЬКО ПОТОМ
# access.has("hr.calendar.view"/"hr.calendar.manage") (403 "Missing
# permission: ..."). Порт: _visible_access(request, employee_id) ниже
# буквально воспроизводит этот порядок, переиспользуя
# _require_visible_employee (employees section выше).
#
# Путь-параметр ``day`` — у исходника это pydantic ``date`` (FastAPI сам
# отдаёт 422 на невалидный формат); Django не имеет встроенного date-
# конвертера пути. Решение брифа: строковый конвертер (``<str:day>``) +
# ручной парсинг в вьюхе (``_parse_day``) — И порядок объявления в urls.py
# (литеральные сегменты ``templates``/``working-days``/``import``/
# ``shift-patterns`` — ДО generic ``<str:day>``, иначе строковый конвертер
# перехватил бы их первым).


def _parse_day(value: str):
    """(date, None) | (None, err) — err готов к возврату (422) на невалидный формат."""
    try:
        return datetime.date.fromisoformat(value), None
    except ValueError:
        return None, json_error(f"Invalid date: {value!r}, expected YYYY-MM-DD", 422)


def _visible_access(request, employee_id: int):
    """(access, None) | (None, err) — порт _visible(employee_id, db,
    current_user) роутера исходника (БЕЗ финальной проверки конкретного
    permission-ключа — её делает вызывающая вьюха, ровно как в исходнике)."""
    try:
        access = hr_access.require_hr_access(hr_access.resolve_hr_access(request.token))
    except hr_access.HRAccessDenied as exc:
        return None, json_error(exc.detail, 403)
    try:
        _require_visible_employee(employee_id, access)
    except emp_svc.EmployeeNotFound:
        return None, json_error("Employee not found", 404)
    return access, None


# ── /calendar/templates/ (литеральный сегмент — ДО /calendar/<str:day>) ────

@api_view(methods=("GET",), auth="jwt")
def _list_calendar_templates(request):
    _, err = _require_permission(request, CALENDAR_VIEW)
    if err:
        return err
    return [cal_svc.template_out(t) for t in cal_svc.list_templates()]


@api_view(methods=("POST",), auth="jwt", body=schemas.WeekTemplateIn, status=201)
def _create_calendar_template(request, data: schemas.WeekTemplateIn):
    _, err = _require_permission(request, CALENDAR_MANAGE)
    if err:
        return err
    tmpl = cal_svc.create_template(data.name, data.model_dump()["days"])
    return cal_svc.template_out(tmpl)


def calendar_templates_collection(request):
    if request.method == "GET":
        return _list_calendar_templates(request)
    if request.method == "POST":
        return _create_calendar_template(request)
    return json_error("Method Not Allowed", 405)


# ── /calendar/templates/{id} ────────────────────────────────────────────────

@api_view(methods=("PUT",), auth="jwt", body=schemas.WeekTemplateIn)
def _update_calendar_template(request, template_id: int, data: schemas.WeekTemplateIn):
    _, err = _require_permission(request, CALENDAR_MANAGE)
    if err:
        return err
    try:
        tmpl = cal_svc.update_template(template_id, data.name, data.model_dump()["days"])
    except cal_svc.TemplateNotFound:
        return json_error("Template not found", 404)
    return cal_svc.template_out(tmpl)


@api_view(methods=("DELETE",), auth="jwt")
def _delete_calendar_template(request, template_id: int):
    _, err = _require_permission(request, CALENDAR_MANAGE)
    if err:
        return err
    try:
        cal_svc.delete_template(template_id)
    except cal_svc.TemplateNotFound:
        return json_error("Template not found", 404)
    except cal_svc.CannotDeleteDefaultTemplate:
        return json_error("Cannot delete the default template", 409)
    return HttpResponse(status=204)


def calendar_template_detail(request, template_id: int):
    if request.method == "PUT":
        return _update_calendar_template(request, template_id=template_id)
    if request.method == "DELETE":
        return _delete_calendar_template(request, template_id=template_id)
    return json_error("Method Not Allowed", 405)


# ── /calendar/templates/{id}/default ────────────────────────────────────────

@api_view(methods=("POST",), auth="jwt")
def calendar_template_set_default(request, template_id: int):
    _, err = _require_permission(request, CALENDAR_MANAGE)
    if err:
        return err
    try:
        tmpl = cal_svc.set_default(template_id)
    except cal_svc.TemplateNotFound:
        return json_error("Template not found", 404)
    return cal_svc.template_out(tmpl)


# ── /calendar/working-days ───────────────────────────────────────────────────

@api_view(methods=("GET",), auth="jwt")
def calendar_working_days(request):
    _, err = _require_permission(request, CALENDAR_VIEW)
    if err:
        return err
    try:
        query = schemas.CalendarWorkingDaysQuery.model_validate(dict(request.GET.items()))
    except ValidationError as exc:
        return _query_error(exc)
    return cal_svc.working_days_between(query.start, query.end)


# ── /calendar/import ─────────────────────────────────────────────────────────

@api_view(methods=("POST",), auth="jwt", body=schemas.CalendarImportBody)
def calendar_import_year(request, data: schemas.CalendarImportBody):
    _, err = _require_permission(request, CALENDAR_MANAGE)
    if err:
        return err
    items = [
        {"day": it.day, "day_type": it.day_type, "norm_hours": it.norm_hours, "note": it.note}
        for it in data.root
    ]
    return {"imported": cal_svc.import_year(items)}


# ── GET /calendar/ (год целиком) ─────────────────────────────────────────────

@api_view(methods=("GET",), auth="jwt")
def calendar_year(request):
    _, err = _require_permission(request, CALENDAR_VIEW)
    if err:
        return err
    try:
        query = schemas.CalendarYearQuery.model_validate(dict(request.GET.items()))
    except ValidationError as exc:
        return _query_error(exc)
    return cal_svc.list_year(query.year)


# ── /calendar/shift-patterns/ ────────────────────────────────────────────────

@api_view(methods=("GET",), auth="jwt")
def _list_shift_patterns(request):
    _, err = _require_permission(request, CALENDAR_VIEW)
    if err:
        return err
    return [cal_svc.shift_pattern_out(p) for p in cal_svc.list_shift_patterns()]


@api_view(methods=("POST",), auth="jwt", body=schemas.ShiftPatternIn, status=201)
def _create_shift_pattern(request, data: schemas.ShiftPatternIn):
    _, err = _require_permission(request, CALENDAR_MANAGE)
    if err:
        return err
    slots = [s.model_dump() for s in data.slots]
    pat = cal_svc.create_shift_pattern(data.name, slots, holidays_off=data.holidays_off)
    return cal_svc.shift_pattern_out(pat)


def shift_patterns_collection(request):
    if request.method == "GET":
        return _list_shift_patterns(request)
    if request.method == "POST":
        return _create_shift_pattern(request)
    return json_error("Method Not Allowed", 405)


# ── /calendar/shift-patterns/{id} ────────────────────────────────────────────

@api_view(methods=("PUT",), auth="jwt", body=schemas.ShiftPatternIn)
def _update_shift_pattern(request, pattern_id: int, data: schemas.ShiftPatternIn):
    _, err = _require_permission(request, CALENDAR_MANAGE)
    if err:
        return err
    slots = [s.model_dump() for s in data.slots]
    try:
        pat = cal_svc.update_shift_pattern(pattern_id, data.name, slots, data.holidays_off)
    except cal_svc.ShiftPatternNotFound:
        return json_error("Shift pattern not found", 404)
    return cal_svc.shift_pattern_out(pat)


@api_view(methods=("DELETE",), auth="jwt")
def _delete_shift_pattern(request, pattern_id: int):
    _, err = _require_permission(request, CALENDAR_MANAGE)
    if err:
        return err
    try:
        cal_svc.delete_shift_pattern(pattern_id)
    except cal_svc.ShiftPatternNotFound:
        return json_error("Shift pattern not found", 404)
    return HttpResponse(status=204)


def shift_pattern_detail(request, pattern_id: int):
    if request.method == "PUT":
        return _update_shift_pattern(request, pattern_id=pattern_id)
    if request.method == "DELETE":
        return _delete_shift_pattern(request, pattern_id=pattern_id)
    return json_error("Method Not Allowed", 405)


# ── /calendar/{day} — национальный оверрайд (все литералы выше уже
#    объявлены — см. urls.py — поэтому generic <str:day> их не перехватит) ──

@api_view(methods=("PUT",), auth="jwt", body=schemas.CalendarDayIn)
def _put_calendar_override(request, day: str, data: schemas.CalendarDayIn):
    _, err = _require_permission(request, CALENDAR_MANAGE)
    if err:
        return err
    d, err = _parse_day(day)
    if err:
        return err
    o = cal_svc.upsert_day(d, data.day_type, data.norm_hours, data.note)
    return cal_svc.day_override_out(o)


@api_view(methods=("DELETE",), auth="jwt")
def _delete_calendar_override(request, day: str):
    _, err = _require_permission(request, CALENDAR_MANAGE)
    if err:
        return err
    d, err = _parse_day(day)
    if err:
        return err
    cal_svc.delete_override(d)
    return HttpResponse(status=204)


def calendar_day_override_detail(request, day: str):
    if request.method == "PUT":
        return _put_calendar_override(request, day=day)
    if request.method == "DELETE":
        return _delete_calendar_override(request, day=day)
    return json_error("Method Not Allowed", 405)


# ── /employees/{id}/calendar — employee_calendar_router исходника (6) ──────

@api_view(methods=("GET",), auth="jwt")
def employee_calendar(request, employee_id: int):
    access, err = _visible_access(request, employee_id)
    if err:
        return err
    if not access.has(CALENDAR_VIEW):
        return json_error(f"Missing permission: {CALENDAR_VIEW}", 403)
    try:
        query = schemas.EmployeeCalendarQuery.model_validate(dict(request.GET.items()))
    except ValidationError as exc:
        return _query_error(exc)
    return cal_svc.employee_calendar(employee_id, query.start, query.end)


@api_view(methods=("PUT",), auth="jwt", body=schemas.AssignTemplateIn)
def employee_calendar_template(request, employee_id: int, data: schemas.AssignTemplateIn):
    access, err = _visible_access(request, employee_id)
    if err:
        return err
    if not access.has(CALENDAR_MANAGE):
        return json_error(f"Missing permission: {CALENDAR_MANAGE}", 403)
    try:
        cal_svc.assign_template(employee_id, data.week_template_id)
    except cal_svc.TemplateNotFound:
        return json_error("Template not found", 404)
    return {"employee_id": employee_id, "week_template_id": data.week_template_id}


@api_view(methods=("PUT",), auth="jwt", body=schemas.AssignShiftIn)
def _assign_employee_shift(request, employee_id: int, data: schemas.AssignShiftIn):
    access, err = _visible_access(request, employee_id)
    if err:
        return err
    if not access.has(CALENDAR_MANAGE):
        return json_error(f"Missing permission: {CALENDAR_MANAGE}", 403)
    try:
        cal_svc.assign_shift(employee_id, data.shift_pattern_id, data.anchor_date)
    except cal_svc.ShiftPatternNotFound:
        return json_error("Shift pattern not found", 404)
    return {
        "employee_id": employee_id,
        "shift_pattern_id": data.shift_pattern_id,
        "anchor_date": data.anchor_date.isoformat(),
    }


@api_view(methods=("DELETE",), auth="jwt")
def _unassign_employee_shift(request, employee_id: int):
    access, err = _visible_access(request, employee_id)
    if err:
        return err
    if not access.has(CALENDAR_MANAGE):
        return json_error(f"Missing permission: {CALENDAR_MANAGE}", 403)
    cal_svc.unassign_shift(employee_id)
    return HttpResponse(status=204)


def employee_shift_detail(request, employee_id: int):
    if request.method == "PUT":
        return _assign_employee_shift(request, employee_id=employee_id)
    if request.method == "DELETE":
        return _unassign_employee_shift(request, employee_id=employee_id)
    return json_error("Method Not Allowed", 405)


@api_view(methods=("PUT",), auth="jwt", body=schemas.EmployeeDayOverrideIn)
def _put_employee_day_override(request, employee_id: int, day: str, data: schemas.EmployeeDayOverrideIn):
    access, err = _visible_access(request, employee_id)
    if err:
        return err
    if not access.has(CALENDAR_MANAGE):
        return json_error(f"Missing permission: {CALENDAR_MANAGE}", 403)
    d, err = _parse_day(day)
    if err:
        return err
    o = cal_svc.set_employee_day_override(employee_id, d, data.day_type, data.norm_hours, data.note)
    return cal_svc.day_override_out(o)


@api_view(methods=("DELETE",), auth="jwt")
def _delete_employee_day_override(request, employee_id: int, day: str):
    access, err = _visible_access(request, employee_id)
    if err:
        return err
    if not access.has(CALENDAR_MANAGE):
        return json_error(f"Missing permission: {CALENDAR_MANAGE}", 403)
    d, err = _parse_day(day)
    if err:
        return err
    cal_svc.delete_employee_day_override(employee_id, d)
    return HttpResponse(status=204)


def employee_day_override_detail(request, employee_id: int, day: str):
    if request.method == "PUT":
        return _put_employee_day_override(request, employee_id=employee_id, day=day)
    if request.method == "DELETE":
        return _delete_employee_day_override(request, employee_id=employee_id, day=day)
    return json_error("Method Not Allowed", 405)


# ═══════════════════════════════════════════════════════════════════════════
#  /documents/* — порт services/hr/app/api/v1/documents.py (4 эндпойнта,
#  модель Document / hr_document)
# ═══════════════════════════════════════════════════════════════════════════
#
# Авторизация — БУКВАЛЬНО как в исходнике: ВСЕ 4 эндпойнта (включая POST и
# DELETE) используют только ``get_current_user`` — исходник НЕ зовёт
# ``require_hr_write`` нигде в documents.py (странность, как у recruiting/
# time-core — см. document_service.py докстринг), поэтому ВСЕ 4 —
# ``api_view(auth="jwt")`` без ``admin=True``.

@api_view(methods=("GET",), auth="jwt")
def _list_documents(request):
    try:
        query = schemas.DocumentListQuery.model_validate(dict(request.GET.items()))
    except ValidationError as exc:
        return _query_error(exc)
    items, total = doc_svc.list_documents(page=query.page, limit=query.limit)
    return doc_svc.paginate(
        [doc_svc.serialize(d) for d in items], total=total, page=query.page, limit=query.limit,
    )


@api_view(methods=("POST",), auth="jwt", body=schemas.DocumentCreate, status=201)
def _upload_document(request, data: schemas.DocumentCreate):
    return doc_svc.serialize(doc_svc.create_document(data))


def documents_collection(request):
    if request.method == "GET":
        return _list_documents(request)
    if request.method == "POST":
        return _upload_document(request)
    return json_error("Method Not Allowed", 405)


@api_view(methods=("GET",), auth="jwt")
def _get_document(request, id: int):
    try:
        return doc_svc.serialize(doc_svc.get_document(id))
    except doc_svc.DocumentNotFound:
        return json_error("Document not found", 404)


@api_view(methods=("DELETE",), auth="jwt")
def _delete_document(request, id: int):
    try:
        doc_svc.delete_document(id)
    except doc_svc.DocumentNotFound:
        return json_error("Document not found", 404)
    return HttpResponse(status=204)


def document_detail(request, id: int):
    if request.method == "GET":
        return _get_document(request, id=id)
    if request.method == "DELETE":
        return _delete_document(request, id=id)
    return json_error("Method Not Allowed", 405)


# ═══════════════════════════════════════════════════════════════════════════
#  /mongo-documents/* — порт services/hr/app/api/v1/mongo_documents.py
#  (5 эндпойнтов, ex-Mongo коллекция hr_documents → EmployeeDocumentBlob
#  JSONB, решение D6)
# ═══════════════════════════════════════════════════════════════════════════
#
# Авторизация — БУКВАЛЬНО как в исходнике: reads (list/get) =
# ``get_current_user`` -> ``api_view(auth="jwt")``; writes (create/update/
# delete) = ``require_hr_write`` (``current_user.is_elevated``) ->
# ``api_view(auth="jwt", admin=True)`` — та же пара, что у positions/org.
#
# ``_require_collection`` 503-деградация исходника (пустой ``mongo_uri``) не
# переносится — Postgres не бывает "не настроен" так, как опциональный Mongo
# (см. document_service.py докстринг).

@api_view(methods=("GET",), auth="jwt")
def _list_mongo_documents(request):
    try:
        query = schemas.MongoDocumentListQuery.model_validate(dict(request.GET.items()))
    except ValidationError as exc:
        return _query_error(exc)
    # Голый список — НЕ PaginatedResponse-конверт (буквально как в исходнике:
    # response_model=list[HRDocumentOut], без items/total/page/pages).
    return doc_svc.list_mongo_documents(
        employee_id=query.employee_id, doc_type=query.doc_type, page=query.page, limit=query.limit,
    )


@api_view(methods=("POST",), auth="jwt", admin=True, body=schemas.HRDocumentCreate, status=201)
def _create_mongo_document(request, data: schemas.HRDocumentCreate):
    return doc_svc.create_mongo_document(data, created_by_user_id=request.token.user_id)


def mongo_documents_collection(request):
    if request.method == "GET":
        return _list_mongo_documents(request)
    if request.method == "POST":
        return _create_mongo_document(request)
    return json_error("Method Not Allowed", 405)


@api_view(methods=("GET",), auth="jwt")
def _get_mongo_document(request, doc_id: str):
    pk = doc_svc.parse_blob_id(doc_id)
    if pk is None:
        return json_error("Invalid document ID format", 400)
    out = doc_svc.get_mongo_document(pk)
    if out is None:
        return json_error("Document not found", 404)
    return out


@api_view(methods=("PATCH",), auth="jwt", admin=True, body=schemas.HRDocumentUpdate)
def _update_mongo_document(request, doc_id: str, data: schemas.HRDocumentUpdate):
    pk = doc_svc.parse_blob_id(doc_id)
    if pk is None:
        return json_error("Invalid document ID format", 400)
    out = doc_svc.update_mongo_document(pk, data)
    if out is None:
        return json_error("Document not found", 404)
    return out


@api_view(methods=("DELETE",), auth="jwt", admin=True)
def _delete_mongo_document(request, doc_id: str):
    pk = doc_svc.parse_blob_id(doc_id)
    if pk is None:
        return json_error("Invalid document ID format", 400)
    if not doc_svc.delete_mongo_document(pk):
        return json_error("Document not found", 404)
    return HttpResponse(status=204)


def mongo_document_detail(request, doc_id: str):
    if request.method == "GET":
        return _get_mongo_document(request, doc_id=doc_id)
    if request.method == "PATCH":
        return _update_mongo_document(request, doc_id=doc_id)
    if request.method == "DELETE":
        return _delete_mongo_document(request, doc_id=doc_id)
    return json_error("Method Not Allowed", 405)


# ═══════════════════════════════════════════════════════════════════════════
#  /employees/{id}/card/t2, /employees/{id}/card/groups — порт
#  services/hr/app/api/v1/employee_card.py (4 эндпойнта, отдельный роутер
#  исходника с prefix "/employees" — модель hr_employee_card/EmployeeCard).
#  ``/employees/me/card`` и ``/employees/{id}/card`` (employees.py исходника)
#  живут в секции /employees/* выше, у my_pmos/employee_pmos — это ТА ЖЕ
#  пара эндпойнтов, что в исходнике (build_card целиком, а не только t2).
# ═══════════════════════════════════════════════════════════════════════════
#
# Auth — ``_visible_access`` (определена выше, секция /calendar/*): БУКВАЛЬНО
# ``_visible_employee`` роутера исходника (``require_hr_access(await
# resolve_hr_access(...))`` + ``EmployeeService.get_employee`` +
# ``can_see_department`` -> 404 "Employee not found") — тот же хелпер, что уже
# используют employee_calendar*, переиспользуется буквально, не дублируется.
#
# Полевой RBAC-гейтинг Т-2 секций (financial/personal/certs) — ВНУТРИ
# ``card_t2_svc.read_sections``/``upsert``
# (``apps/hr/services/employee_card_t2_service.py::_SECTIONS`` — секция
# видна/редактируема ТОЛЬКО при ``access.has(<view|edit_key>)``); вьюха здесь
# не знает об отдельных Т-2-ключах и не решает, что показать — ровно как
# роутер исходника (``EmployeeCardT2Service(db).read_sections(...)``/
# ``.upsert(...)`` без единой permission-проверки в самом роутере). ``groups``
# — единственный permission-ключ на весь ресурс (``hr.card.groups.view``/
# ``hr.card.groups.edit``), проверяется прямо во вьюхе — буквальный порт
# ``if not access.has("hr.card.groups.view"/"edit"): raise 403`` роутера.


@api_view(methods=("GET",), auth="jwt")
def _get_card_t2(request, employee_id: int):
    access, err = _visible_access(request, employee_id)
    if err:
        return err
    return card_t2_svc.read_sections(employee_id, access)


@api_view(methods=("PATCH",), auth="jwt", body=schemas.EmployeeCardT2Patch)
def _patch_card_t2(request, employee_id: int, data: schemas.EmployeeCardT2Patch):
    access, err = _visible_access(request, employee_id)
    if err:
        return err
    patch = data.model_dump(exclude_unset=True)
    try:
        return card_t2_svc.upsert(employee_id, patch, access)
    except PermissionError as exc:
        return json_error(str(exc), 403)
    except ValueError as exc:
        return json_error(str(exc), 422)


def card_t2_detail(request, employee_id: int):
    if request.method == "GET":
        return _get_card_t2(request, employee_id=employee_id)
    if request.method == "PATCH":
        return _patch_card_t2(request, employee_id=employee_id)
    return json_error("Method Not Allowed", 405)


@api_view(methods=("GET",), auth="jwt")
def _get_card_groups(request, employee_id: int):
    access, err = _visible_access(request, employee_id)
    if err:
        return err
    if not access.has(CARD_GROUPS_VIEW):
        return json_error(f"Missing permission: {CARD_GROUPS_VIEW}", 403)
    return groups_svc.read(employee_id)


@api_view(methods=("PUT",), auth="jwt", body=schemas.EmployeeGroupsIn)
def _put_card_groups(request, employee_id: int, data: schemas.EmployeeGroupsIn):
    access, err = _visible_access(request, employee_id)
    if err:
        return err
    if not access.has(CARD_GROUPS_EDIT):
        return json_error(f"Missing permission: {CARD_GROUPS_EDIT}", 403)
    return groups_svc.replace(employee_id, data.model_dump(mode="json"))


def card_groups_detail(request, employee_id: int):
    if request.method == "GET":
        return _get_card_groups(request, employee_id=employee_id)
    if request.method == "PUT":
        return _put_card_groups(request, employee_id=employee_id)
    return json_error("Method Not Allowed", 405)


# ═══════════════════════════════════════════════════════════════════════════
#  /pmo/* — порт services/hr/app/api/v1/pmo.py (10 эндпойнтов, модели
#  PMO/PMODepartment/PMOPosition/PMOMember — hr_pmo/hr_pmodepartment/
#  hr_pmoposition/hr_pmomember)
# ═══════════════════════════════════════════════════════════════════════════
#
# Авторизация (решение брифа): reads (get_current_user исходника) ->
# auth="jwt"; writes (require_hr_write исходника, is_elevated) ->
# api_view(admin=True) — та же пара, что у departments/positions/org.
#
# update_pmo — ТОЛЬКО PATCH в исходнике (@router.patch("/{id}")), в отличие
# от departments/positions/employees/vacancies/applications/time-tracking, у
# которых порт аддитивно регистрирует и PUT рядом (там был живой мисматч с
# фронтом). frontend/src/api/hr.ts НЕ шлёт ни один запрос на /pmo/* (только
# TS-интерфейсы EmployeePmoEntry/EmployeeCard.pmos для employees-эндпойнтов
# выше) — живого мисматча нет, поэтому здесь регистрируется буквально ТОЛЬКО
# PATCH, без добавления PUT.
#
# add_pmo_member/update_pmo_member — заголовок X-Allocation-Warning
# (суммарная загрузка сотрудника по всем активным PMO > 100%) добавляется
# ТОЛЬКО поверх готового JsonResponse (api_view не даёт добавить заголовок к
# dict-результату — см. htqweb/http.py: "готовый HttpResponse ... status
# игнорируется", тот же приём здесь для заголовков).

# ── /pmo/ — коллекция ────────────────────────────────────────────────────

@api_view(methods=("GET",), auth="jwt")
def _list_pmos(request):
    return pmo_svc.list_pmos(status_filter=request.GET.get("status") or None)


@api_view(methods=("POST",), auth="jwt", admin=True, body=schemas.PMOCreate, status=201)
def _create_pmo(request, data: schemas.PMOCreate):
    try:
        pmo = pmo_svc.create_pmo(data.model_dump())
    except pmo_svc.PMOCodeExists as exc:
        return json_error(exc.detail, 409)
    return pmo_svc.serialize(pmo)


def pmo_collection(request):
    if request.method == "GET":
        return _list_pmos(request)
    if request.method == "POST":
        return _create_pmo(request)
    return json_error("Method Not Allowed", 405)


# ── /pmo/{id}/ — детальный ресурс ────────────────────────────────────────

@api_view(methods=("GET",), auth="jwt")
def _get_pmo(request, id: int):
    try:
        return pmo_svc.serialize(pmo_svc.get_pmo(id))
    except pmo_svc.PMONotFound:
        return json_error("PMO not found", 404)


@api_view(methods=("PATCH",), auth="jwt", admin=True, body=schemas.PMOUpdate)
def _update_pmo(request, id: int, data: schemas.PMOUpdate):
    try:
        pmo = pmo_svc.update_pmo(id, data.model_dump(exclude_none=True))
    except pmo_svc.PMONotFound:
        return json_error("PMO not found", 404)
    return pmo_svc.serialize(pmo)


@api_view(methods=("DELETE",), auth="jwt", admin=True)
def _delete_pmo(request, id: int):
    try:
        pmo_svc.delete_pmo(id)
    except pmo_svc.PMONotFound:
        return json_error("PMO not found", 404)
    return HttpResponse(status=204)


def pmo_detail(request, id: int):
    if request.method == "GET":
        return _get_pmo(request, id=id)
    if request.method == "PATCH":
        return _update_pmo(request, id=id)
    if request.method == "DELETE":
        return _delete_pmo(request, id=id)
    return json_error("Method Not Allowed", 405)


# ── /pmo/{id}/members ─────────────────────────────────────────────────────

@api_view(methods=("GET",), auth="jwt")
def _list_pmo_members(request, id: int):
    try:
        return pmo_svc.list_members(id)
    except pmo_svc.PMONotFound:
        return json_error("PMO not found", 404)


@api_view(methods=("POST",), auth="jwt", admin=True, body=schemas.PMOMemberAdd)
def _add_pmo_member(request, id: int, data: schemas.PMOMemberAdd):
    try:
        member, warning_total = pmo_svc.add_member(
            id, data.model_dump(), actor_user_id=request.token.user_id,
        )
    except pmo_svc.PMONotFound:
        return json_error("PMO not found", 404)
    except pmo_svc.PMOClosed as exc:
        return json_error(exc.detail, 409)
    except pmo_svc.EmployeeNotFound:
        return json_error("Employee not found", 404)
    except pmo_svc.PMOMemberDatesInvalid as exc:
        return json_error(exc.detail, 422)
    except pmo_svc.PMOMemberDuplicateActive as exc:
        return json_error(exc.detail, 409)
    except pmo_svc.PMOMemberPrimaryExists as exc:
        return json_error(exc.detail, 409)
    resp = JsonResponse(pmo_svc.serialize_member_created(member), status=201)
    if warning_total > 100:
        resp["X-Allocation-Warning"] = str(warning_total)
    return resp


def pmo_members_collection(request, id: int):
    if request.method == "GET":
        return _list_pmo_members(request, id=id)
    if request.method == "POST":
        return _add_pmo_member(request, id=id)
    return json_error("Method Not Allowed", 405)


# ── /pmo/{id}/members/{member_id} ────────────────────────────────────────

@api_view(methods=("PATCH",), auth="jwt", admin=True, body=schemas.PMOMemberUpdate)
def _update_pmo_member(request, id: int, member_id: int, data: schemas.PMOMemberUpdate):
    try:
        member, warning_total = pmo_svc.update_member(
            id, member_id, data.model_dump(exclude_unset=True), actor_user_id=request.token.user_id,
        )
    except pmo_svc.PMOMemberNotFound:
        return json_error("Member not found in this PMO", 404)
    except pmo_svc.EmployeeNotFound:
        return json_error("Employee not found", 404)
    except pmo_svc.PMOMemberDatesInvalid as exc:
        return json_error(exc.detail, 422)
    except pmo_svc.PMOMemberDuplicateActive as exc:
        return json_error(exc.detail, 409)
    except pmo_svc.PMOMemberPrimaryExists as exc:
        return json_error(exc.detail, 409)
    resp = JsonResponse(pmo_svc.serialize_member_created(member), status=200)
    if warning_total > 100:
        resp["X-Allocation-Warning"] = str(warning_total)
    return resp


@api_view(methods=("DELETE",), auth="jwt", admin=True)
def _remove_pmo_member(request, id: int, member_id: int):
    try:
        pmo_svc.remove_member(id, member_id)
    except pmo_svc.PMOMemberNotFound:
        return json_error("Member not found in this PMO", 404)
    return HttpResponse(status=204)


def pmo_member_detail(request, id: int, member_id: int):
    if request.method == "PATCH":
        return _update_pmo_member(request, id=id, member_id=member_id)
    if request.method == "DELETE":
        return _remove_pmo_member(request, id=id, member_id=member_id)
    return json_error("Method Not Allowed", 405)


# ── /pmo/{id}/org-chart ───────────────────────────────────────────────────

@api_view(methods=("GET",), auth="jwt")
def pmo_org_chart(request, id: int):
    try:
        return pmo_svc.get_pmo_org_chart(id)
    except pmo_svc.PMONotFound:
        return json_error("PMO not found", 404)


# ═══════════════════════════════════════════════════════════════════════════
#  final: /share-links/*, /public/{org,employee}/{token}, /department-*/*,
#  /logs/, /internal/supervisor — порт services/hr/app/api/v1/{share_links,
#  department_files,audit,internal}.py + app/api/public/{org,employee}.py.
#  Последний под-модуль домена hr.
# ═══════════════════════════════════════════════════════════════════════════
#
# Авторизация (решение контроллера, брифа под-модуля final) — разнобой,
# сверено с каждым эндпойнтом исходника отдельно:
#   * share-links (управление) — ``get_current_user`` исходника -> обычный
#     ``auth="jwt"`` на ВСЕХ 4 (включая POST/DELETE — исходник НЕ зовёт
#     require_hr_write здесь: любой залогиненный может создать/отозвать
#     СВОЮ ссылку, get_link/list_audit сами гейтят по created_by_user_id);
#   * /public/org/{token}, /public/employee/{token} — БЕЗ JWT вовсе
#     (``auth=None``): доступ по знанию токена ссылки, проверка внутри
#     share_link_service;
#   * department-files/department-file-folders — ``get_current_user`` +
#     собственный department-based access-check (НЕ hr_access.HRAccess,
#     НЕ require_permission — самостоятельная авторизационная модель
#     исходника, отдел сотрудника == department_id ИЛИ is_elevated);
#   * /logs/ (audit) — обычный ``get_current_user`` -> auth="jwt", БЕЗ
#     admin=True — любой залогиненный видит весь журнал (буквальный порт,
#     странность исходника, не баг);
#   * /internal/supervisor — S2S, НЕ JWT: общий секрет в заголовке
#     ``X-Internal-Token`` (``auth=None`` + ручная проверка), буквальный порт
#     ``require_internal_token`` исходника.


# ── /share-links/ — коллекция ────────────────────────────────────────────────

def _share_link_public_path(target_type: str) -> str:
    return "/public/employee/" if target_type == "employee" else "/public/org/"


def _share_link_public_url(request, raw_token: str, target_type: str = "org") -> str:
    """Строит user-facing публичный URL — порт ``_public_url`` роутера
    исходника. ``settings.public_base_url`` исходника не имеет здесь прямого
    аналога (Django-настройки этой аппки его не заводят — граница задачи
    ограничена ``backend/apps/hr/**``); ``getattr`` с дефолтом воспроизводит
    тот же "нет — падаем на следующий уровень" фолбэк, что и исходник."""
    path = _share_link_public_path(target_type)
    base = getattr(django_settings, "PUBLIC_BASE_URL", None)
    if base:
        return f"{base.rstrip('/')}{path}{raw_token}"

    fwd_host = (request.headers.get("x-forwarded-host") or "").split(",")[0].strip()
    if fwd_host:
        proto = (request.headers.get("x-forwarded-proto") or request.scheme).split(",")[0].strip()
        return f"{proto}://{fwd_host}{path}{raw_token}"

    return f"{request.scheme}://{request.get_host()}{path}{raw_token}"


@api_view(methods=("POST",), auth="jwt", body=schemas.ShareLinkCreate, status=201)
def _create_share_link(request, data: schemas.ShareLinkCreate):
    try:
        created = share_link_svc.create_link(request.token.user_id, data.model_dump())
    except share_link_svc.TargetEmployeeRequired:
        return json_error("target_employee_id is required when target_type='employee'", 422)
    out = share_link_svc.serialize_link(created.link)
    out["token"] = created.raw_token
    out["url"] = _share_link_public_url(request, created.raw_token, created.link.target_type or "org")
    return out


@api_view(methods=("GET",), auth="jwt")
def _list_share_links(request):
    return [share_link_svc.serialize_link(link) for link in share_link_svc.list_links(request.token.user_id)]


def share_links_collection(request):
    if request.method == "GET":
        return _list_share_links(request)
    if request.method == "POST":
        return _create_share_link(request)
    return json_error("Method Not Allowed", 405)


# ── /share-links/{id} ─────────────────────────────────────────────────────

@api_view(methods=("DELETE",), auth="jwt")
def share_link_detail(request, link_id):
    try:
        share_link_svc.revoke_link(link_id, request.token.user_id)
    except share_link_svc.LinkNotFound:
        return json_error("Link not found", 404)
    return HttpResponse(status=204)


# ── /share-links/{id}/audit ───────────────────────────────────────────────

@api_view(methods=("GET",), auth="jwt")
def share_link_audit(request, link_id):
    """Forensic-трейл одной ссылки. Только владельцу."""
    try:
        entries = share_link_svc.list_audit(link_id, request.token.user_id)
    except share_link_svc.LinkNotFound:
        return json_error("Link not found", 404)
    return [share_link_svc.serialize_audit_entry(e) for e in entries]


# ── /public/org/{token}, /public/employee/{token} — БЕЗ JWT ───────────────

def _public_consume_error(exc: Exception):
    if isinstance(exc, share_link_svc.LinkNotFound):
        return json_error("Link not found", 404)
    if isinstance(exc, share_link_svc.LinkRevoked):
        return json_error("This link has been revoked", 410)
    if isinstance(exc, share_link_svc.LinkAlreadyUsed):
        return json_error("This one-time link has already been used", 410)
    if isinstance(exc, share_link_svc.LinkExpired):
        return json_error("This link has expired", 410)
    if isinstance(exc, share_link_svc.LinkInactive):
        return json_error("This link is no longer active", 410)
    if isinstance(exc, share_link_svc.EmployeeLinkGone):
        return json_error("The employee referenced by this link no longer exists", 410)
    raise exc


def _public_json_response(result: dict) -> JsonResponse:
    # X-Robots-Tag/Cache-Control — порт заголовков роутера исходника
    # (защита от индексации + запрет кеширования). Возвращаем готовый
    # HttpResponse напрямую (не dict) — api_view передаёт такие объекты как
    # есть, не оборачивая повторно (см. htqweb/http.py).
    response = JsonResponse(result)
    response["X-Robots-Tag"] = "noindex, nofollow"
    response["Cache-Control"] = "no-store"
    return response


@api_view(methods=("GET",), auth=None)
def public_org_view(request, token: str):
    try:
        result = share_link_svc.consume_link(request, token)
    except (
        share_link_svc.LinkNotFound,
        share_link_svc.LinkRevoked,
        share_link_svc.LinkAlreadyUsed,
        share_link_svc.LinkExpired,
        share_link_svc.LinkInactive,
    ) as exc:
        return _public_consume_error(exc)
    return _public_json_response(result)


@api_view(methods=("GET",), auth=None)
def public_employee_view(request, token: str):
    try:
        result = share_link_svc.consume_employee_link(request, token)
    except (
        share_link_svc.LinkNotFound,
        share_link_svc.LinkRevoked,
        share_link_svc.LinkAlreadyUsed,
        share_link_svc.LinkExpired,
        share_link_svc.LinkInactive,
        share_link_svc.EmployeeLinkGone,
    ) as exc:
        return _public_consume_error(exc)
    return _public_json_response(result)


# ── /department-folders/ ─────────────────────────────────────────────────

@api_view(methods=("GET",), auth="jwt")
def department_folders_list(request):
    return dept_file_svc.list_department_folders(request.token)


# ── /department-files/search/ (литеральный роут — ДО коллекции) ────────────

@api_view(methods=("GET",), auth="jwt")
def department_files_search(request):
    try:
        query = schemas.DepartmentFileSearchQuery.model_validate(dict(request.GET.items()))
    except ValidationError as exc:
        return _query_error(exc)
    return dept_file_svc.search_department_files(request.token, query.q, limit=query.limit)


# ── /department-file-folders/ — коллекция ───────────────────────────────────

@api_view(methods=("GET",), auth="jwt")
def _list_department_file_folders(request):
    try:
        query = schemas.DepartmentQuery.model_validate(dict(request.GET.items()))
    except ValidationError as exc:
        return _query_error(exc)
    try:
        return dept_file_svc.list_department_file_folders(request.token, query.department)
    except dept_file_svc.DepartmentNotFound:
        return json_error("Department not found", 404)
    except dept_file_svc.DepartmentAccessDenied:
        return json_error("Department access denied", 403)


@api_view(methods=("POST",), auth="jwt", body=schemas.DepartmentFileFolderCreate, status=201)
def _create_department_file_folder(request, data: schemas.DepartmentFileFolderCreate):
    try:
        return dept_file_svc.create_department_file_folder(request.token, data.department, data.name)
    except dept_file_svc.DepartmentNotFound:
        return json_error("Department not found", 404)
    except dept_file_svc.DepartmentAccessDenied:
        return json_error("Department access denied", 403)
    except dept_file_svc.FolderNameRequired:
        return json_error("Folder name is required", 400)
    except dept_file_svc.FolderAlreadyExists:
        return json_error("Folder already exists", 409)


def department_file_folders_collection(request):
    if request.method == "GET":
        return _list_department_file_folders(request)
    if request.method == "POST":
        return _create_department_file_folder(request)
    return json_error("Method Not Allowed", 405)


# ── /department-files/ — коллекция ───────────────────────────────────────

@api_view(methods=("GET",), auth="jwt")
def _list_department_files(request):
    try:
        query = schemas.DepartmentFileListQuery.model_validate(dict(request.GET.items()))
    except ValidationError as exc:
        return _query_error(exc)
    try:
        return dept_file_svc.list_department_files(
            request.token, folder=query.folder, file_folder=query.file_folder, root_only=query.root_only,
        )
    except dept_file_svc.DepartmentNotFound:
        return json_error("Department not found", 404)
    except dept_file_svc.DepartmentAccessDenied:
        return json_error("Department access denied", 403)
    except dept_file_svc.FileFolderNotFound:
        return json_error("File folder not found", 404)


@api_view(methods=("POST",), auth="jwt", status=201)
def _upload_department_file(request):
    # multipart/form-data — POST Django сам парсит в request.POST/request.FILES
    # (в отличие от PATCH, см. apps/users/views.py::_parse_multipart_patch).
    try:
        folder = int(request.POST.get("folder", ""))
    except (TypeError, ValueError):
        return json_error({"folder": "field required"}, 422)

    file_folder_raw = request.POST.get("file_folder")
    file_folder: int | None = None
    if file_folder_raw not in (None, ""):
        try:
            file_folder = int(file_folder_raw)
        except (TypeError, ValueError):
            return json_error({"file_folder": "must be an integer"}, 422)

    upload = request.FILES.get("file")
    if upload is None:
        return json_error({"file": "field required"}, 422)

    description = request.POST.get("description", "")

    try:
        return dept_file_svc.upload_department_file(
            request.token, folder=folder, file_folder=file_folder, file=upload, description=description,
        )
    except dept_file_svc.DepartmentNotFound:
        return json_error("Department not found", 404)
    except dept_file_svc.DepartmentAccessDenied:
        return json_error("Department access denied", 403)
    except dept_file_svc.FileFolderNotFound:
        return json_error("File folder not found", 404)
    except dept_file_svc.UploadRejected as exc:
        return json_error(exc.detail, exc.status_code)


def department_files_collection(request):
    if request.method == "GET":
        return _list_department_files(request)
    if request.method == "POST":
        return _upload_department_file(request)
    return json_error("Method Not Allowed", 405)


# ── /department-files/{id}/ ──────────────────────────────────────────────

@api_view(methods=("DELETE",), auth="jwt")
def department_file_detail(request, file_id: int):
    try:
        dept_file_svc.delete_department_file(request.token, file_id)
    except dept_file_svc.DepartmentFileNotFound:
        return json_error("Department file not found", 404)
    except dept_file_svc.DepartmentAccessDenied:
        return json_error("Department access denied", 403)
    return HttpResponse(status=204)


# ── /logs/ — порт audit.py ────────────────────────────────────────────────

@api_view(methods=("GET",), auth="jwt")
def audit_logs(request):
    try:
        query = schemas.AuditLogQuery.model_validate(dict(request.GET.items()))
    except ValidationError as exc:
        return _query_error(exc)
    return audit_service.list_logs(
        entity_type=query.entity_type, entity_id=query.entity_id, page=query.page, limit=query.limit,
    )


# ── /internal/supervisor — S2S, БЕЗ JWT ────────────────────────────────────

def _check_internal_token(request):
    """None — авторизован; иначе готовый json_error. Буквальный порт
    ``require_internal_token`` исходника: общий секрет
    ``INTERNAL_S2S_TOKEN`` (или legacy ``MESSENGER_INTERNAL_TOKEN`` на время
    перехода) сверяется с заголовком ``X-Internal-Token``."""
    expected = os.environ.get("INTERNAL_S2S_TOKEN") or os.environ.get("MESSENGER_INTERNAL_TOKEN") or ""
    if not expected:
        return json_error("INTERNAL_S2S_TOKEN not configured", 503)
    got = request.headers.get("X-Internal-Token")
    if not got or got != expected:
        return json_error("invalid internal token", 401)
    return None


@api_view(methods=("GET",), auth=None)
def internal_supervisor(request):
    err = _check_internal_token(request)
    if err is not None:
        return err
    try:
        query = schemas.InternalSupervisorQuery.model_validate(dict(request.GET.items()))
    except ValidationError as exc:
        return _query_error(exc)
    return {"supervisor_user_id": internal_svc.get_supervisor_user_id(query.user_id)}
