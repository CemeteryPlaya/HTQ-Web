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

from . import access as hr_access
from . import schemas
from .permissions import LEVEL_PRESETS
from .services import department_service as svc
from .services import employee_service as emp_svc
from .services import org_service
from .services import position_service as pos_svc
from .services import recruitment_service as rec_svc


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
#  /employees/* — порт services/hr/app/api/v1/employees.py (9 из 16
#  эндпойнтов; 7 отложены — см. брифы hr-misc/hr-docs/apps.users.interface,
#  растяжки в tests/test_employees_api.py)
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
