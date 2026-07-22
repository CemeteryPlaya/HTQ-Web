"""Контракт /api/hr/v1/staffing/* — паритет с services/hr/app/api/v1/staffing.py.

Провенанс формы ответов: app/schemas/staffing.py (StaffingLineOut), поведение
— app/services/staffing_service.py.

Авторизация (docs/plans/2026-07-20-hr-domain.md, под-модуль time-core) — ВАЖНО,
это НЕ грубый api_view(admin=True) (positions/org) и НЕ тонкий
require_hr_access/require_can_write_basic (employees). Исходник грепом не
светит Depends напрямую в сигнатуре — они вынесены в module-level константы
``_VIEW = require_permission("hr.staffing.view")``, ``_MANAGE =
require_permission("hr.staffing.manage")`` (app/api/v1/staffing.py). Это
fine-grained PERMISSION-KEY проверка (app/auth/hr_access.py::require_permission):
403 detail — ТОЧНАЯ строка f"Missing permission: {key}", не "HR access
required"/"HR write access required" (которые несёт HRAccessDenied в
employees/apps.hr.access). Порт: occupancy/summary/list -> access.has(
"hr.staffing.view"); create/update/delete -> access.has("hr.staffing.manage").

Зафиксированные ловушки паритета (проверяются тестами ниже):
  * headcount/salary/fot СТРОКАМИ (не float), квантованы до 2 знаков;
  * PUT — единственный метод записи детального ресурса (в исходнике нет
    отдельной Update-схемы — StaffingLineIn используется и для create, и для
    update, тело всегда ПОЛНОЕ); фронт (frontend/src/api/hr.ts) не шлёт
    PATCH на /staffing/{id} — PATCH НЕ регистрируем (нет живого мисматча);
  * create/update 422 при несуществующем position_id/department_id;
  * occupancy/summary — агрегации, форма ответа буквально как в исходнике.

План: docs/plans/2026-07-20-hr-domain.md
"""
from __future__ import annotations

import datetime

import pytest
from django.test import Client

from apps.hr.models import Department, Employee, Position, StaffingPosition
from apps.users.models import User, UserStatus
from htqweb.authn.jwt import issue_token_pair

BASE = "/api/hr/v1/staffing"


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
def hr_dep(db):
    return _dep("HR", "hr")


@pytest.fixture
def admin_auth(db):
    """is_staff=True -> HRAccess(level='lead', permissions={'*'}) — имеет
    и hr.staffing.view, и hr.staffing.manage."""
    _user, headers = _user_auth("hr-admin@htq.test", is_staff=True)
    return headers


@pytest.fixture
def no_access_auth(db):
    """Обычный вошедший без Employee-профиля — HRAccess() пустой, нет
    hr.staffing.view/manage вообще."""
    _user, headers = _user_auth("plain@htq.test")
    return headers


@pytest.fixture
def middle_auth(db, hr_dep):
    """middle level (LEVEL_PRESETS._MIDDLE) НЕ включает hr.staffing.view —
    появляется только с senior. Должен получить 403 "Missing permission:
    hr.staffing.view" на чтениях."""
    pos = _pos("HR Manager", hr_dep, weight=20)
    user, headers = _user_auth("hr-middle@htq.test")
    Employee.objects.create(
        first_name="И", last_name="И", email="hr-middle@htq.test",
        department=hr_dep, position=pos, hire_date=datetime.date(2024, 1, 9), user_id=user.id,
    )
    return headers


@pytest.fixture
def senior_auth(db, hr_dep):
    """senior level -> LEVEL_PRESETS._SENIOR включает и hr.staffing.view, и
    hr.staffing.manage (см. apps/hr/permissions.py)."""
    pos = _pos("Senior HR Manager", hr_dep, weight=30)
    user, headers = _user_auth("hr-senior@htq.test")
    Employee.objects.create(
        first_name="И", last_name="И", email="hr-senior@htq.test",
        department=hr_dep, position=pos, hire_date=datetime.date(2024, 1, 9), user_id=user.id,
    )
    return headers


def _line(pos, dep, **kw):
    return StaffingPosition.objects.create(position=pos, department=dep, **kw)


# ── auth: permission-key gate (НЕ HRAccessDenied, НЕ admin=True) ────────────

@pytest.mark.django_db
def test_requires_jwt_at_all():
    assert Client().get(f"{BASE}/").status_code == 401


@pytest.mark.django_db
def test_no_hr_access_forbidden_with_missing_permission_detail(no_access_auth):
    resp = Client().get(f"{BASE}/", **no_access_auth)
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Missing permission: hr.staffing.view"


@pytest.mark.django_db
def test_middle_level_lacks_staffing_view(middle_auth):
    """middle level не включает hr.staffing.view (только с senior) —
    буквальный порт LEVEL_PRESETS."""
    resp = Client().get(f"{BASE}/", **middle_auth)
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Missing permission: hr.staffing.view"


@pytest.mark.django_db
def test_senior_level_can_view_and_manage(senior_auth, pos, dep):
    assert Client().get(f"{BASE}/", **senior_auth).status_code == 200
    resp = Client().post(
        f"{BASE}/", data={"position_id": pos.id, "department_id": dep.id},
        content_type="application/json", **senior_auth,
    )
    assert resp.status_code == 201


@pytest.mark.django_db
def test_view_permission_insufficient_for_manage(senior_auth):
    """Даже senior (view+manage) отличается от чисто-view сценария: с ТОЛЬКО
    view (без manage) create/update/delete должны 403. Симулируется явной
    матрицей прав на должности."""
    dep_ = _dep("HR2", "hr2")
    pos_ = _pos("View Only", dep_, weight=1, permissions={"permissions": ["hr.staffing.view"]})
    user, headers = _user_auth("view-only@htq.test")
    Employee.objects.create(
        first_name="И", last_name="И", email="view-only@htq.test",
        department=dep_, position=pos_, hire_date=datetime.date(2024, 1, 9), user_id=user.id,
    )
    assert Client().get(f"{BASE}/", **headers).status_code == 200
    resp = Client().post(
        f"{BASE}/", data={"position_id": 1, "department_id": 1},
        content_type="application/json", **headers,
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Missing permission: hr.staffing.manage"


# ── GET /staffing/ — список (headcount/salary/fot строками) ─────────────────

@pytest.mark.django_db
def test_list_lines_serializes_decimals_as_quantized_strings(admin_auth, pos, dep):
    _line(pos, dep, headcount="2.5", salary="1000")

    resp = Client().get(f"{BASE}/", **admin_auth)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    line = body[0]
    assert line["headcount"] == "2.50"
    assert line["salary"] == "1000.00"
    assert line["fot"] == "2500.00"
    assert set(line) == {"id", "position_id", "department_id", "grade", "headcount",
                         "salary", "fot", "note"}


@pytest.mark.django_db
def test_list_lines_filters_by_department_id(admin_auth, pos, dep):
    other_dep = _dep("Финансы", "fin")
    _line(pos, dep)
    _line(pos, other_dep)

    resp = Client().get(f"{BASE}/?department_id={dep.id}", **admin_auth)
    body = resp.json()
    assert len(body) == 1
    assert body[0]["department_id"] == dep.id


# ── POST /staffing/ — create ─────────────────────────────────────────────

@pytest.mark.django_db
def test_create_line_defaults_headcount_and_salary(admin_auth, pos, dep):
    resp = Client().post(
        f"{BASE}/", data={"position_id": pos.id, "department_id": dep.id},
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["headcount"] == "1.00"
    assert body["salary"] == "0.00"
    assert body["fot"] == "0.00"


@pytest.mark.django_db
def test_create_line_missing_position_422(admin_auth, dep):
    resp = Client().post(
        f"{BASE}/", data={"position_id": 999999, "department_id": dep.id},
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == "Position not found"


@pytest.mark.django_db
def test_create_line_missing_department_422(admin_auth, pos):
    resp = Client().post(
        f"{BASE}/", data={"position_id": pos.id, "department_id": 999999},
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == "Department not found"


# ── PUT /staffing/{id} — update (без trailing slash в исходнике) ────────────

@pytest.mark.django_db
def test_update_line_full_body(admin_auth, pos, dep):
    line = _line(pos, dep, headcount="1", salary="0")
    resp = Client().put(
        f"{BASE}/{line.id}",
        data={"position_id": pos.id, "department_id": dep.id, "headcount": "3", "salary": "500"},
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["headcount"] == "3.00"
    assert body["fot"] == "1500.00"


@pytest.mark.django_db
def test_update_line_not_found_404(admin_auth, pos, dep):
    resp = Client().put(
        f"{BASE}/999999", data={"position_id": pos.id, "department_id": dep.id},
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Staffing line not found"


# ── DELETE /staffing/{id} ────────────────────────────────────────────────

@pytest.mark.django_db
def test_delete_line_204(admin_auth, pos, dep):
    line = _line(pos, dep)
    resp = Client().delete(f"{BASE}/{line.id}", **admin_auth)
    assert resp.status_code == 204
    assert not StaffingPosition.objects.filter(id=line.id).exists()


@pytest.mark.django_db
def test_delete_line_not_found_404(admin_auth):
    resp = Client().delete(f"{BASE}/999999", **admin_auth)
    assert resp.status_code == 404


# ── GET /staffing/occupancy ───────────────────────────────────────────────

@pytest.mark.django_db
def test_occupancy_computes_vacant_from_budget_minus_filled(admin_auth, pos, dep):
    _line(pos, dep, headcount="3")
    Employee.objects.create(
        first_name="А", last_name="А", email="a1@htq.test", department=dep, position=pos,
        hire_date=datetime.date(2024, 1, 9), status="active",
    )

    resp = Client().get(f"{BASE}/occupancy", **admin_auth)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    row = body[0]
    assert row["position_id"] == pos.id
    assert row["department_id"] == dep.id
    assert row["budgeted"] == "3.00"
    assert row["filled"] == 1
    assert row["vacant"] == "2.00"


@pytest.mark.django_db
def test_occupancy_clamps_negative_vacancy_to_zero(admin_auth, pos, dep):
    _line(pos, dep, headcount="1")
    for i in range(3):
        Employee.objects.create(
            first_name="А", last_name=f"{i}", email=f"a{i}@htq.test", department=dep, position=pos,
            hire_date=datetime.date(2024, 1, 9), status="active",
        )
    resp = Client().get(f"{BASE}/occupancy", **admin_auth)
    assert resp.json()[0]["vacant"] == "0.00"


@pytest.mark.django_db
def test_occupancy_ignores_soft_deleted_and_inactive_employees(admin_auth, pos, dep):
    _line(pos, dep, headcount="5")
    Employee.objects.create(
        first_name="А", last_name="А", email="del@htq.test", department=dep, position=pos,
        hire_date=datetime.date(2024, 1, 9), status="active", is_deleted=True,
    )
    Employee.objects.create(
        first_name="Б", last_name="Б", email="inactive@htq.test", department=dep, position=pos,
        hire_date=datetime.date(2024, 1, 9), status="terminated",
    )
    resp = Client().get(f"{BASE}/occupancy", **admin_auth)
    assert resp.json()[0]["filled"] == 0


# ── GET /staffing/summary ─────────────────────────────────────────────────

@pytest.mark.django_db
def test_summary_aggregates_fot_by_department(admin_auth, pos, dep):
    other_dep = _dep("Финансы", "fin")
    other_pos = _pos("Бухгалтер", other_dep, weight=50)
    _line(pos, dep, headcount="2", salary="1000")
    _line(other_pos, other_dep, headcount="1", salary="2000")

    resp = Client().get(f"{BASE}/summary", **admin_auth)
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"by_department", "total_fot", "total_budgeted",
                         "total_filled", "total_vacant"}
    assert body["total_fot"] == "4000.00"
    assert body["total_budgeted"] == "3.00"
    by_dept = {row["department_id"]: row["fot"] for row in body["by_department"]}
    assert by_dept[dep.id] == "2000.00"
    assert by_dept[other_dep.id] == "2000.00"
