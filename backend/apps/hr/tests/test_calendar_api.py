"""Контракт /api/hr/v1/calendar/* + /api/hr/v1/employees/{id}/calendar* —
паритет с services/hr/app/api/v1/calendar.py (14 + 6 = 20 эндпойнтов: 14 в
router "/calendar", 6 в employee_calendar_router "/employees").

Провенанс формы ответов: app/schemas/calendar.py (WeekTemplateOut,
ShiftPatternOut) + inline-словари роутера (put/{day}, working-days, import,
assign-template, assign-shift). Поведение — app/services/calendar_service.py.

Авторизация (docs/plans/2026-07-20-hr-domain.md) — ДВЕ разные схемы в одном
модуле, порт БУКВАЛЬНО:
  * /calendar/* (14 эндпойнтов): module-level ``_VIEW``/``_MANAGE`` исходника
    (require_permission("hr.calendar.view"/"hr.calendar.manage")) —
    fine-grained PERMISSION-KEY, 403 detail ТОЧНАЯ строка
    f"Missing permission: {key}" (как staffing, НЕ HRAccessDenied);
  * /employees/{id}/calendar* (6 эндпойнтов): ``_visible()`` роутера —
    СНАЧАЛА require_hr_access (403 "HR access required" при полном отсутствии
    HR-доступа, ДАЖЕ если employee_id не существует — порядок проверок важен),
    ЗАТЕМ get_employee + can_see_department (404 "Employee not found" и за
    несуществующего, и за невидимого сотрудника), ТОЛЬКО ПОТОМ
    access.has("hr.calendar.view"/"hr.calendar.manage") (403 "Missing
    permission: ...").

Зафиксированные ловушки паритета (проверяются тестами ниже):
  * literal-segment routes (templates/working-days/import/shift-patterns)
    матчатся РАНЬШЕ generic <str:day> — иначе "templates" парсился бы как день;
  * PUT/DELETE /calendar/{day} — норм_hours в ОТВЕТЕ строкой (day_override_out),
    а не float (в отличие от day_info()["hours"] списка /calendar/?year=);
  * POST /calendar/import — тело ЦЕЛИКОМ JSON-массив (RootModel), не объект;
  * DELETE /calendar/templates/{id} на дефолтном шаблоне -> 409;
  * assign_shift/assign_template — взаимоисключающи (снимают друг друга).

План: docs/plans/2026-07-20-hr-domain.md
"""
from __future__ import annotations

import datetime

import pytest
from django.test import Client

from apps.hr.models import (
    CalendarDay,
    Department,
    Employee,
    EmployeeShiftAssignment,
    EmployeeWeekTemplate,
    Position,
    ShiftPattern,
    WeekTemplate,
)
from apps.users.models import User, UserStatus
from htqweb.authn.jwt import issue_token_pair

BASE = "/api/hr/v1/calendar"
EMP_BASE = "/api/hr/v1/employees"

_FIVE_TWO = {str(i): {"type": "working", "hours": 8} for i in range(5)}
_FIVE_TWO.update({"5": {"type": "weekend", "hours": 0}, "6": {"type": "weekend", "hours": 0}})


def _dep(name, path, **kw):
    return Department.objects.create(name=name, path=path, **kw)


def _pos(title, dep, weight, **kw):
    return Position.objects.create(title=title, department=dep, weight=weight, **kw)


def _user_auth(email, *, is_staff=False):
    user = User.objects.create(
        username=email.split("@")[0], email=email, password="x", status=UserStatus.ACTIVE,
        is_staff=is_staff,
    )
    user.set_password("S3cret!Pass1")
    user.save()
    return user, {"HTTP_AUTHORIZATION": f"Bearer {issue_token_pair(user)['access']}"}


@pytest.fixture
def dep(db):
    return _dep("ИТ", "it")


@pytest.fixture
def pos(db, dep):
    return _pos("Инженер", dep, weight=100)


@pytest.fixture
def emp(db, dep, pos):
    return Employee.objects.create(
        first_name="И", last_name="И", email="emp-cal@htq.test", department=dep, position=pos,
        hire_date=datetime.date(2024, 1, 9),
    )


@pytest.fixture
def hr_dep(db):
    return _dep("HR", "hr")


@pytest.fixture
def admin_auth(db):
    """is_staff=True -> HRAccess(level='lead', permissions={'*'}) — и
    hr.calendar.view, и hr.calendar.manage, и can_read_all."""
    _user, headers = _user_auth("cal-admin@htq.test", is_staff=True)
    return headers


@pytest.fixture
def no_access_auth(db):
    """Обычный вошедший без Employee-профиля — HRAccess() пустой."""
    _user, headers = _user_auth("cal-noacc@htq.test")
    return headers


@pytest.fixture
def middle_auth(db, hr_dep):
    """middle level: hr.calendar.view есть (все уровни), hr.calendar.manage
    нет (только senior/lead) — apps/hr/permissions.py::_MIDDLE/_SENIOR."""
    pos = _pos("HR Manager", hr_dep, weight=20)
    user, headers = _user_auth("cal-middle@htq.test")
    Employee.objects.create(
        first_name="И", last_name="И", email="cal-middle@htq.test",
        department=hr_dep, position=pos, hire_date=datetime.date(2024, 1, 9), user_id=user.id,
    )
    return headers


@pytest.fixture
def senior_auth(db, hr_dep):
    """senior level -> и view, и manage, и can_read_all (EMPLOYEES_VIEW_ALL
    входит в _SENIOR) — видит сотрудников ЛЮБОГО отдела."""
    pos = _pos("Senior HR Manager", hr_dep, weight=30)
    user, headers = _user_auth("cal-senior@htq.test")
    Employee.objects.create(
        first_name="И", last_name="И", email="cal-senior@htq.test",
        department=hr_dep, position=pos, hire_date=datetime.date(2024, 1, 9), user_id=user.id,
    )
    return headers


def _template(**kw):
    kw.setdefault("name", "5/2")
    kw.setdefault("days", _FIVE_TWO)
    return WeekTemplate.objects.create(**kw)


# ═════════════════════ /calendar/* — auth: permission-key gate ═════════════

@pytest.mark.django_db
def test_requires_jwt_at_all():
    assert Client().get(f"{BASE}/templates/").status_code == 401


@pytest.mark.django_db
def test_no_hr_access_forbidden_with_missing_permission_detail(no_access_auth):
    resp = Client().get(f"{BASE}/templates/", **no_access_auth)
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Missing permission: hr.calendar.view"


@pytest.mark.django_db
def test_middle_has_view_but_not_manage(middle_auth, dep):
    assert Client().get(f"{BASE}/templates/", **middle_auth).status_code == 200
    resp = Client().post(
        f"{BASE}/templates/", data={"name": "X", "days": _FIVE_TWO},
        content_type="application/json", **middle_auth,
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Missing permission: hr.calendar.manage"


@pytest.mark.django_db
def test_senior_can_view_and_manage(senior_auth):
    assert Client().get(f"{BASE}/templates/", **senior_auth).status_code == 200
    resp = Client().post(
        f"{BASE}/templates/", data={"name": "X", "days": _FIVE_TWO},
        content_type="application/json", **senior_auth,
    )
    assert resp.status_code == 201


# ═════════════════════ /calendar/templates/ ═════════════════════════════════

@pytest.mark.django_db
def test_list_templates_shape(admin_auth):
    _template()
    resp = Client().get(f"{BASE}/templates/", **admin_auth)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert set(body[0]) == {"id", "name", "is_default", "days"}


@pytest.mark.django_db
def test_create_template_requires_keys_0_to_6(admin_auth):
    bad_days = {str(i): {"type": "working", "hours": 8} for i in range(5)}  # только 0..4
    resp = Client().post(
        f"{BASE}/templates/", data={"name": "bad", "days": bad_days},
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 422


@pytest.mark.django_db
def test_create_template_rejects_unknown_type(admin_auth):
    days = dict(_FIVE_TWO)
    days["0"] = {"type": "holiday", "hours": 8}  # holiday недопустим для шаблона
    resp = Client().post(
        f"{BASE}/templates/", data={"name": "bad", "days": days},
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 422


@pytest.mark.django_db
def test_update_template_not_found_404(admin_auth):
    resp = Client().put(
        f"{BASE}/templates/999999/", data={"name": "x", "days": _FIVE_TWO},
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Template not found"


@pytest.mark.django_db
def test_delete_default_template_409(admin_auth):
    t = _template(is_default=True)
    resp = Client().delete(f"{BASE}/templates/{t.id}", **admin_auth)
    assert resp.status_code == 409
    assert resp.json()["detail"] == "Cannot delete the default template"


@pytest.mark.django_db
def test_delete_non_default_template_204(admin_auth):
    t = _template(is_default=False)
    resp = Client().delete(f"{BASE}/templates/{t.id}", **admin_auth)
    assert resp.status_code == 204
    assert not WeekTemplate.objects.filter(id=t.id).exists()


@pytest.mark.django_db
def test_set_default_moves_flag(admin_auth):
    t1 = _template(name="A", is_default=True)
    t2 = _template(name="B", is_default=False)
    resp = Client().post(f"{BASE}/templates/{t2.id}/default", **admin_auth)
    assert resp.status_code == 200
    assert resp.json()["is_default"] is True
    t1.refresh_from_db()
    assert t1.is_default is False


@pytest.mark.django_db
def test_set_default_not_found_404(admin_auth):
    resp = Client().post(f"{BASE}/templates/999999/default", **admin_auth)
    assert resp.status_code == 404


# ═════════════════════ /calendar/working-days ═══════════════════════════════

@pytest.mark.django_db
def test_working_days_endpoint(admin_auth):
    _template(is_default=True)
    resp = Client().get(
        f"{BASE}/working-days", {"start": "2026-06-01", "end": "2026-06-07"}, **admin_auth,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["working_days"] == 5
    # Pure Python Decimal(str(float)) accumulation (нет round-trip через
    # NUMERIC(4,2)-колонку — working_days_between не трогает БД) — "40.0",
    # НЕ "40.00" (в отличие от put_override ниже, где значение реально идёт
    # через NUMERIC(4,2)).
    assert body["norm_hours"] == "40.0"


@pytest.mark.django_db
def test_working_days_missing_query_422(admin_auth):
    resp = Client().get(f"{BASE}/working-days", **admin_auth)
    assert resp.status_code == 422


# ═════════════════════ /calendar/import — RootModel (список целиком) ═══════

@pytest.mark.django_db
def test_import_year_body_is_bare_json_array(admin_auth):
    payload = [
        {"day": "2026-01-01", "day_type": "holiday", "norm_hours": 0, "note": "NY"},
        {"day": "2026-01-07", "day_type": "holiday", "norm_hours": 0},
    ]
    resp = Client().post(
        f"{BASE}/import", data=payload, content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 200, resp.content
    assert resp.json() == {"imported": 2}
    assert CalendarDay.objects.filter(day="2026-01-01", day_type="holiday").exists()


# ═════════════════════ GET /calendar/ (year) ═════════════════════════════════

@pytest.mark.django_db
def test_get_year_reflects_override(admin_auth):
    _template(is_default=True)
    p = Client().put(
        f"{BASE}/2026-06-01", data={"day_type": "holiday", "norm_hours": 0, "note": "X"},
        content_type="application/json", **admin_auth,
    )
    assert p.status_code == 200, p.content
    y = Client().get(f"{BASE}/", {"year": 2026}, **admin_auth)
    assert y.status_code == 200
    jun1 = next(d for d in y.json() if d["day"] == "2026-06-01")
    assert jun1["type"] == "holiday"


@pytest.mark.django_db
def test_get_year_missing_query_422(admin_auth):
    resp = Client().get(f"{BASE}/", **admin_auth)
    assert resp.status_code == 422


# ═════════════════════ /calendar/{day} — PUT/DELETE override ═══════════════

@pytest.mark.django_db
def test_put_override_response_shape_norm_hours_is_string(admin_auth):
    resp = Client().put(
        f"{BASE}/2026-06-01", data={"day_type": "holiday", "norm_hours": 0, "note": "X"},
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 200
    body = resp.json()
    # norm_hours через NUMERIC(4,2)-колонку (DecimalField(max_digits=4,
    # decimal_places=2)) -> "0.00", НЕ "0" (в отличие от чистого Python-
    # вычисления working-days выше).
    assert body == {"day": "2026-06-01", "day_type": "holiday", "norm_hours": "0.00", "note": "X"}


@pytest.mark.django_db
def test_delete_override_204(admin_auth):
    CalendarDay.objects.create(day=datetime.date(2026, 6, 1), day_type="holiday", norm_hours=0)
    resp = Client().delete(f"{BASE}/2026-06-01", **admin_auth)
    assert resp.status_code == 204
    assert not CalendarDay.objects.filter(day="2026-06-01").exists()


@pytest.mark.django_db
def test_put_override_rejects_unknown_day_type_422(admin_auth):
    resp = Client().put(
        f"{BASE}/2026-06-01", data={"day_type": "bogus", "norm_hours": 0},
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 422


# ── ordering: литералы НЕ перехватываются generic <str:day> ────────────────

@pytest.mark.django_db
def test_literal_routes_not_swallowed_by_day_catchall(admin_auth):
    assert Client().get(f"{BASE}/templates/", **admin_auth).status_code == 200
    assert Client().get(f"{BASE}/shift-patterns/", **admin_auth).status_code == 200
    assert Client().get(
        f"{BASE}/working-days", {"start": "2026-01-01", "end": "2026-01-01"}, **admin_auth,
    ).status_code == 200


@pytest.mark.django_db
def test_put_override_invalid_date_returns_422_not_500(admin_auth):
    resp = Client().put(
        f"{BASE}/not-a-date", data={"day_type": "holiday", "norm_hours": 0},
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 422


# ═════════════════════ /calendar/shift-patterns/* ═══════════════════════════

@pytest.mark.django_db
def test_create_shift_pattern_shape(admin_auth):
    resp = Client().post(
        f"{BASE}/shift-patterns/",
        data={"name": "2/2", "slots": [{"type": "work", "hours": 12}, {"type": "off", "hours": 0}]},
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert set(body) == {"id", "name", "slots", "holidays_off"}
    assert body["holidays_off"] is False


@pytest.mark.django_db
def test_create_shift_pattern_requires_at_least_one_slot(admin_auth):
    resp = Client().post(
        f"{BASE}/shift-patterns/", data={"name": "empty", "slots": []},
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 422


@pytest.mark.django_db
def test_update_shift_pattern_not_found_404(admin_auth):
    resp = Client().put(
        f"{BASE}/shift-patterns/999999/",
        data={"name": "x", "slots": [{"type": "work", "hours": 8}]},
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Shift pattern not found"


@pytest.mark.django_db
def test_delete_shift_pattern_204(admin_auth):
    p = ShiftPattern.objects.create(name="P", slots=[{"type": "work", "hours": 8}])
    resp = Client().delete(f"{BASE}/shift-patterns/{p.id}", **admin_auth)
    assert resp.status_code == 204
    assert not ShiftPattern.objects.filter(id=p.id).exists()


# ═════════════════════ /employees/{id}/calendar* — _visible() ordering ═════

@pytest.mark.django_db
def test_employee_scoped_requires_jwt(emp):
    resp = Client().get(f"{EMP_BASE}/{emp.id}/calendar", {"start": "2026-06-01", "end": "2026-06-01"})
    assert resp.status_code == 401


@pytest.mark.django_db
def test_employee_scoped_hr_access_required_even_for_nonexistent_employee(no_access_auth):
    """Порядок исходника: require_hr_access ПЕРЕД get_employee — 403 "HR
    access required", НЕ 404, даже если employee_id вообще не существует."""
    resp = Client().get(
        f"{EMP_BASE}/999999/calendar", {"start": "2026-06-01", "end": "2026-06-01"}, **no_access_auth,
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "HR access required"


@pytest.mark.django_db
def test_employee_scoped_404_for_missing_employee(admin_auth):
    resp = Client().get(
        f"{EMP_BASE}/999999/calendar", {"start": "2026-06-01", "end": "2026-06-01"}, **admin_auth,
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Employee not found"


@pytest.mark.django_db
def test_employee_scoped_404_for_invisible_department(hr_dep, dep, emp):
    """Скоуп-ограниченный HR (без hr.employees.view.all) видит только СВОЙ
    отдел — сотрудник из другого отдела отдаёт 404, не 403 (не раскрываем
    существование)."""
    scoped_pos = _pos(
        "Calendar Manager", hr_dep, weight=15,
        permissions={"permissions": ["hr.calendar.view", "hr.calendar.manage"]},
    )
    user, headers = _user_auth("cal-scoped@htq.test")
    Employee.objects.create(
        first_name="И", last_name="И", email="cal-scoped@htq.test",
        department=hr_dep, position=scoped_pos, hire_date=datetime.date(2024, 1, 9), user_id=user.id,
    )
    resp = Client().get(
        f"{EMP_BASE}/{emp.id}/calendar", {"start": "2026-06-01", "end": "2026-06-01"}, **headers,
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Employee not found"


@pytest.mark.django_db
def test_employee_scoped_missing_calendar_view_permission(hr_dep, emp):
    """Видимый (свой отдел = чужого нет, can_read_all) сотрудник, но explicit
    permissions без hr.calendar.view -> 403 "Missing permission:
    hr.calendar.view" (ПОСЛЕ прохождения _visible)."""
    scoped_pos = _pos(
        "No Calendar", hr_dep, weight=16,
        permissions={"permissions": ["hr.employees.view.all"]},
    )
    user, headers = _user_auth("cal-nocal@htq.test")
    Employee.objects.create(
        first_name="И", last_name="И", email="cal-nocal@htq.test",
        department=hr_dep, position=scoped_pos, hire_date=datetime.date(2024, 1, 9), user_id=user.id,
    )
    resp = Client().get(
        f"{EMP_BASE}/{emp.id}/calendar", {"start": "2026-06-01", "end": "2026-06-01"}, **headers,
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Missing permission: hr.calendar.view"


@pytest.mark.django_db
def test_employee_calendar_returns_resolved_days(admin_auth, emp):
    _template(is_default=True)
    resp = Client().get(
        f"{EMP_BASE}/{emp.id}/calendar", {"start": "2026-06-06", "end": "2026-06-06"}, **admin_auth,
    )
    assert resp.status_code == 200
    assert resp.json()[0]["type"] == "weekend"  # Saturday under 5/2


@pytest.mark.django_db
def test_assign_employee_template_then_calendar_reflects_it(admin_auth, emp):
    _template(is_default=True)
    six_one = {str(i): {"type": "working", "hours": 8} for i in range(6)}
    six_one["6"] = {"type": "weekend", "hours": 0}
    c = Client().post(
        f"{BASE}/templates/", data={"name": "6/1", "days": six_one},
        content_type="application/json", **admin_auth,
    )
    tid = c.json()["id"]
    a = Client().put(
        f"{EMP_BASE}/{emp.id}/calendar-template", data={"week_template_id": tid},
        content_type="application/json", **admin_auth,
    )
    assert a.status_code == 200, a.content
    assert a.json() == {"employee_id": emp.id, "week_template_id": tid}
    g = Client().get(
        f"{EMP_BASE}/{emp.id}/calendar", {"start": "2026-06-06", "end": "2026-06-06"}, **admin_auth,
    )
    assert g.json()[0]["type"] == "working"  # Saturday рабочий под 6/1


@pytest.mark.django_db
def test_assign_employee_template_not_found_404(admin_auth, emp):
    resp = Client().put(
        f"{EMP_BASE}/{emp.id}/calendar-template", data={"week_template_id": 999999},
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Template not found"


@pytest.mark.django_db
def test_assign_and_unassign_shift(admin_auth, emp):
    pattern = ShiftPattern.objects.create(name="1/0", slots=[{"type": "work", "hours": 8}])
    a = Client().put(
        f"{EMP_BASE}/{emp.id}/shift",
        data={"shift_pattern_id": pattern.id, "anchor_date": "2026-06-01"},
        content_type="application/json", **admin_auth,
    )
    assert a.status_code == 200
    assert a.json() == {
        "employee_id": emp.id, "shift_pattern_id": pattern.id, "anchor_date": "2026-06-01",
    }
    assert EmployeeShiftAssignment.objects.filter(employee_id=emp.id).exists()

    d = Client().delete(f"{EMP_BASE}/{emp.id}/shift", **admin_auth)
    assert d.status_code == 204
    assert not EmployeeShiftAssignment.objects.filter(employee_id=emp.id).exists()


@pytest.mark.django_db
def test_assign_shift_not_found_404(admin_auth, emp):
    resp = Client().put(
        f"{EMP_BASE}/{emp.id}/shift",
        data={"shift_pattern_id": 999999, "anchor_date": "2026-06-01"},
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Shift pattern not found"


@pytest.mark.django_db
def test_assign_shift_clears_week_template(admin_auth, emp):
    t = _template(is_default=True)
    Client().put(
        f"{EMP_BASE}/{emp.id}/calendar-template", data={"week_template_id": t.id},
        content_type="application/json", **admin_auth,
    )
    assert EmployeeWeekTemplate.objects.filter(employee_id=emp.id).exists()

    pattern = ShiftPattern.objects.create(name="1/0", slots=[{"type": "work", "hours": 8}])
    Client().put(
        f"{EMP_BASE}/{emp.id}/shift",
        data={"shift_pattern_id": pattern.id, "anchor_date": "2026-06-01"},
        content_type="application/json", **admin_auth,
    )
    assert not EmployeeWeekTemplate.objects.filter(employee_id=emp.id).exists()


@pytest.mark.django_db
def test_employee_day_override_put_and_delete(admin_auth, emp):
    p = Client().put(
        f"{EMP_BASE}/{emp.id}/calendar/2026-06-01",
        data={"day_type": "short", "norm_hours": 4, "note": "half"},
        content_type="application/json", **admin_auth,
    )
    assert p.status_code == 200
    assert p.json() == {"day": "2026-06-01", "day_type": "short", "norm_hours": "4.00", "note": "half"}

    d = Client().delete(f"{EMP_BASE}/{emp.id}/calendar/2026-06-01", **admin_auth)
    assert d.status_code == 204
