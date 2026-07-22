"""Контракт /api/hr/v1/pmo/* — паритет с services/hr/app/api/v1/pmo.py.

Провенанс формы ответов: pmo.py роутера исходника (схемы были inline —
PMOOut/MemberOut/MemberCreatedOut), поведение — app/services/pmo_service.py.
Модель — app/models/pmo.py (4 таблицы: PMO/PMODepartment/PMOPosition/
PMOMember — hr_pmo/hr_pmodepartment/hr_pmoposition/hr_pmomember).

Авторизация (решение брифа): reads = get_current_user исходника -> auth="jwt";
writes = require_hr_write исходника (is_elevated) -> admin=True — та же пара,
что у departments/positions/org.

Зафиксированные ловушки паритета (проверяются тестами ниже):
  * update_pmo — ТОЛЬКО PATCH (буквально исходник, без аддитивного PUT — нет
    живого мисматча с фронтом, см. views.py комментарий);
  * PATCH status="closed" редиректит в soft-close (delete_pmo): PMO не
    исчезает, только status="closed" + все текущие активные членства
    получают to_date=today;
  * add/update member — 409 при повторном активном членстве того же
    сотрудника в этом PMO, 409 при повторном активном is_primary, 422 при
    to_date < from_date, 409 при добавлении в closed PMO;
  * X-Allocation-Warning заголовок на POST/PATCH members при суммарной
    загрузке сотрудника по активным PMO > 100% — не блокирует (201/200);
  * GET /employees/{id}/pmos (test_employees_api.py) и GET /{id}/org-chart
    зовут ту же get_employee_pmos/get_pmo_org_chart логику.

Составной PK (PMODepartment/PMOPosition — models.CompositePrimaryKey) и
частичные уникальные индексы (PMOMember — condition=Q(...)) сверены отдельно
ниже (test_pmo_department_composite_pk_*, test_pmo_member_partial_unique_*).

План: docs/plans/2026-07-20-hr-domain.md
"""
from __future__ import annotations

import datetime

import pytest
from django.db import connection
from django.db.utils import IntegrityError
from django.test import Client

from apps.hr.models import Department, Employee, PMO, PMODepartment, PMOMember, PMOPosition, Position
from apps.users.models import User, UserStatus
from htqweb.authn.jwt import issue_token_pair

BASE = "/api/hr/v1/pmo"
EBASE = "/api/hr/v1/employees"
TODAY = datetime.date.today()


@pytest.fixture
def dep(db):
    return Department.objects.create(name="ИТ", path="it")


@pytest.fixture
def pos(db, dep):
    return Position.objects.create(title="Инженер", department=dep, weight=100)


@pytest.fixture
def emp(db, dep, pos):
    return Employee.objects.create(
        first_name="Иван", last_name="Иванов", email="ivan@htq.test",
        department=dep, position=pos, hire_date=datetime.date(2024, 1, 9),
    )


@pytest.fixture
def emp2(db, dep, pos):
    return Employee.objects.create(
        first_name="Пётр", last_name="Петров", email="petr@htq.test",
        department=dep, position=pos, hire_date=datetime.date(2024, 1, 9),
    )


@pytest.fixture
def auth(db):
    """Обычный вошедший пользователь — годится для reads, НЕ годится для writes."""
    user = User.objects.create(
        username="pmo-user", email="pmo-user@htq.test", password="x", status=UserStatus.ACTIVE,
    )
    user.set_password("S3cret!")
    user.save()
    return {"HTTP_AUTHORIZATION": f"Bearer {issue_token_pair(user)['access']}"}


@pytest.fixture
def admin_auth(db):
    """is_staff=True — elevated, требуется для writes (require_hr_write)."""
    user = User.objects.create(
        username="pmo-admin", email="pmo-admin@htq.test", password="x", status=UserStatus.ACTIVE,
        is_staff=True,
    )
    user.set_password("Adm1n!Pass")
    user.save()
    return {"HTTP_AUTHORIZATION": f"Bearer {issue_token_pair(user)['access']}"}


def _pmo(**kw):
    defaults = {"name": "PMO Alpha", "code": "ALPHA"}
    defaults.update(kw)
    return PMO.objects.create(**defaults)


def _member(pmo, employee, **kw):
    kw.setdefault("from_date", TODAY)
    return PMOMember.objects.create(pmo=pmo, employee=employee, **kw)


# ── схема — сверка колонок/индексов/констрейнтов ────────────────────────────

def _cols(table: str) -> dict:
    with connection.cursor() as cur:
        cur.execute(
            "SELECT column_name, is_nullable, column_default "
            "FROM information_schema.columns WHERE table_name = %s",
            [table],
        )
        return {r[0]: {"nullable": r[1] == "YES", "default": r[2]} for r in cur.fetchall()}


def _indexed_columns(table: str) -> set[str]:
    with connection.cursor() as cur:
        cur.execute("SELECT indexdef FROM pg_indexes WHERE tablename = %s", [table])
        defs = [r[0] for r in cur.fetchall()]
    cols: set[str] = set()
    for d in defs:
        inner = d[d.rfind("(") + 1: d.rfind(")")]
        for part in inner.split(","):
            token = part.strip().strip('"').split()[0]
            cols.add(token.strip('"'))
    return cols


@pytest.mark.django_db
def test_pmo_columns_and_indexes():
    cols = _cols("hr_pmo")
    assert not cols["name"]["nullable"]
    assert not cols["code"]["nullable"]
    assert cols["description"]["nullable"]
    assert cols["head_employee_id"]["nullable"]
    assert cols["status"]["default"] is not None
    assert cols["created_at"]["default"] is not None
    assert {"code", "status"} <= _indexed_columns("hr_pmo")


@pytest.mark.django_db
def test_pmo_code_unique():
    _pmo(code="DUP")
    with pytest.raises(IntegrityError):
        PMO.objects.create(name="Other", code="DUP")


@pytest.mark.django_db
def test_pmo_status_check_constraint():
    pmo = _pmo()
    with pytest.raises(IntegrityError):
        PMO.objects.filter(id=pmo.id).update(status="bogus")


@pytest.mark.django_db
def test_pmo_department_composite_pk_prevents_duplicate_pair(dep):
    pmo = _pmo()
    PMODepartment.objects.create(pmo=pmo, department=dep)
    with pytest.raises(IntegrityError):
        PMODepartment.objects.create(pmo=pmo, department=dep)


@pytest.mark.django_db
def test_pmo_department_role_check_constraint(dep):
    pmo = _pmo()
    with pytest.raises(IntegrityError):
        PMODepartment.objects.create(pmo=pmo, department=dep, role="bogus")


@pytest.mark.django_db
def test_pmo_position_composite_pk_prevents_duplicate_pair(pos):
    pmo = _pmo()
    PMOPosition.objects.create(pmo=pmo, position=pos)
    with pytest.raises(IntegrityError):
        PMOPosition.objects.create(pmo=pmo, position=pos)


@pytest.mark.django_db
def test_pmo_member_columns_and_default_indexes():
    cols = _cols("hr_pmomember")
    assert not cols["from_date"]["nullable"]
    assert cols["to_date"]["nullable"]
    assert cols["allocation_percent"]["default"] is not None
    assert cols["is_primary"]["default"] is not None
    assert "created_at" not in cols  # НЕ HrBase (буквально как исходник — Base, не BaseModel)
    # Исходник несёт РОВНО два одиночных индекса: pmo_id, employee_id — Django
    # FK auto-index воспроизводит их без явных пометок.
    assert {"pmo_id", "employee_id"} <= _indexed_columns("hr_pmomember")


@pytest.mark.django_db
def test_pmo_member_type_check_constraint(emp):
    pmo = _pmo()
    with pytest.raises(IntegrityError):
        PMOMember.objects.create(pmo=pmo, employee=emp, from_date=TODAY, membership_type="bogus")


@pytest.mark.django_db
def test_pmo_member_allocation_range_check_constraint(emp):
    pmo = _pmo()
    with pytest.raises(IntegrityError):
        PMOMember.objects.create(pmo=pmo, employee=emp, from_date=TODAY, allocation_percent=101)


@pytest.mark.django_db
def test_pmo_member_dates_check_constraint(emp):
    pmo = _pmo()
    with pytest.raises(IntegrityError):
        PMOMember.objects.create(
            pmo=pmo, employee=emp, from_date=TODAY, to_date=TODAY - datetime.timedelta(days=1),
        )


@pytest.mark.django_db
def test_pmo_member_partial_unique_open_employee(emp):
    """ux_hr_pmo_members_open_employee: не более ОДНОГО открытого
    (to_date IS NULL) членства сотрудника в одном PMO — закрытое не мешает."""
    pmo = _pmo()
    _member(
        pmo, emp, from_date=TODAY - datetime.timedelta(days=5),
        to_date=TODAY - datetime.timedelta(days=1),
    )  # closed — не блокирует
    _member(pmo, emp)  # open — ok
    with pytest.raises(IntegrityError):
        PMOMember.objects.create(pmo=pmo, employee=emp, from_date=TODAY)  # second open — collides


@pytest.mark.django_db
def test_pmo_member_partial_unique_open_primary(emp, emp2):
    """ux_hr_pmo_members_open_primary: не более ОДНОГО открытого первичного
    членства на PMO (по разным сотрудникам)."""
    pmo = _pmo()
    _member(pmo, emp, is_primary=True)
    with pytest.raises(IntegrityError):
        PMOMember.objects.create(pmo=pmo, employee=emp2, from_date=TODAY, is_primary=True)


# ── auth ──────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_list_requires_jwt():
    assert Client().get(f"{BASE}/").status_code == 401


@pytest.mark.django_db
def test_create_forbidden_for_non_admin(auth):
    resp = Client().post(
        f"{BASE}/", data={"name": "X", "code": "X1"}, content_type="application/json", **auth,
    )
    assert resp.status_code == 403


@pytest.mark.django_db
def test_update_forbidden_for_non_admin(auth):
    pmo = _pmo()
    resp = Client().patch(
        f"{BASE}/{pmo.id}/", data={"name": "Y"}, content_type="application/json", **auth,
    )
    assert resp.status_code == 403


@pytest.mark.django_db
def test_delete_forbidden_for_non_admin(auth):
    pmo = _pmo()
    resp = Client().delete(f"{BASE}/{pmo.id}/", **auth)
    assert resp.status_code == 403


@pytest.mark.django_db
def test_add_member_forbidden_for_non_admin(auth, emp):
    pmo = _pmo()
    resp = Client().post(
        f"{BASE}/{pmo.id}/members", data={"employee_id": emp.id},
        content_type="application/json", **auth,
    )
    assert resp.status_code == 403


# ── /pmo/ — коллекция ────────────────────────────────────────────────────

@pytest.mark.django_db
def test_list_ordered_by_name(auth):
    _pmo(name="Zeta", code="Z1")
    _pmo(name="Alpha", code="A1")
    resp = Client().get(f"{BASE}/", **auth)
    assert resp.status_code == 200
    assert [p["name"] for p in resp.json()] == ["Alpha", "Zeta"]


@pytest.mark.django_db
def test_list_filters_by_status(auth):
    _pmo(name="Active PMO", code="A2", status="active")
    _pmo(name="Closed PMO", code="C2", status="closed")
    resp = Client().get(f"{BASE}/?status=closed", **auth)
    assert [p["code"] for p in resp.json()] == ["C2"]


@pytest.mark.django_db
def test_create_returns_201_and_shape(admin_auth, emp):
    resp = Client().post(
        f"{BASE}/",
        data={"name": "PMO New", "code": "NEW1", "head_employee_id": emp.id},
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body == {
        "id": body["id"], "name": "PMO New", "code": "NEW1", "description": None,
        "head_employee_id": emp.id, "status": "active",
    }
    assert PMO.objects.filter(id=body["id"]).exists()


@pytest.mark.django_db
def test_create_duplicate_code_409(admin_auth):
    _pmo(code="DUP2")
    resp = Client().post(
        f"{BASE}/", data={"name": "Other", "code": "DUP2"},
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 409
    assert "DUP2" in resp.json()["detail"]


# ── /pmo/{id}/ — детальный ресурс ────────────────────────────────────────

@pytest.mark.django_db
def test_get_returns_404_for_missing(auth):
    assert Client().get(f"{BASE}/999999/", **auth).status_code == 404


@pytest.mark.django_db
def test_get_returns_pmo(auth):
    pmo = _pmo()
    resp = Client().get(f"{BASE}/{pmo.id}/", **auth)
    assert resp.status_code == 200
    assert resp.json()["code"] == "ALPHA"


@pytest.mark.django_db
def test_update_patches_fields(admin_auth):
    pmo = _pmo()
    resp = Client().patch(
        f"{BASE}/{pmo.id}/", data={"name": "Renamed"}, content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Renamed"
    pmo.refresh_from_db()
    assert pmo.name == "Renamed"


@pytest.mark.django_db
def test_update_status_closed_soft_closes_and_closes_active_members(admin_auth, emp):
    pmo = _pmo()
    member = _member(pmo, emp)

    resp = Client().patch(
        f"{BASE}/{pmo.id}/", data={"status": "closed"}, content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "closed"
    assert PMO.objects.filter(id=pmo.id).exists()  # НЕ физическое удаление
    member.refresh_from_db()
    assert member.to_date == TODAY


@pytest.mark.django_db
def test_delete_soft_closes_pmo_and_closes_active_members(admin_auth, emp, emp2):
    """Порт test_soft_delete_pmo_closes_active_members исходника."""
    pmo = _pmo()
    m1 = _member(pmo, emp)
    m2 = _member(pmo, emp2)

    resp = Client().delete(f"{BASE}/{pmo.id}/", **admin_auth)
    assert resp.status_code == 204

    pmo.refresh_from_db()
    assert pmo.status == "closed"
    m1.refresh_from_db()
    m2.refresh_from_db()
    assert m1.to_date == TODAY
    assert m2.to_date == TODAY


# ── /pmo/{id}/members ─────────────────────────────────────────────────────

@pytest.mark.django_db
def test_list_members_404_for_missing_pmo(auth):
    assert Client().get(f"{BASE}/999999/members", **auth).status_code == 404


@pytest.mark.django_db
def test_list_members_shape(auth, emp):
    pmo = _pmo()
    _member(pmo, emp, position_in_pmo="Lead", allocation_percent=40, is_primary=True)

    resp = Client().get(f"{BASE}/{pmo.id}/members", **auth)
    assert resp.status_code == 200
    [item] = resp.json()
    assert item == {
        "id": item["id"], "pmo_id": pmo.id, "employee_id": emp.id,
        "employee_name": "Иван Иванов", "employee_email": "ivan@htq.test",
        "primary_position": "Инженер", "position_in_pmo": "Lead",
        "membership_type": "permanent", "allocation_percent": 40, "is_primary": True,
        "from_date": TODAY.isoformat(), "to_date": None,
    }


@pytest.mark.django_db
def test_add_member_returns_201_and_shape(admin_auth, emp):
    pmo = _pmo()
    resp = Client().post(
        f"{BASE}/{pmo.id}/members",
        data={"employee_id": emp.id, "allocation_percent": 80, "is_primary": True},
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["allocation_percent"] == 80
    assert body["is_primary"] is True
    assert "X-Allocation-Warning" not in resp.headers
    assert PMOMember.objects.filter(id=body["id"]).exists()


@pytest.mark.django_db
def test_add_member_missing_employee_404(admin_auth):
    pmo = _pmo()
    resp = Client().post(
        f"{BASE}/{pmo.id}/members", data={"employee_id": 999999},
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Employee not found"


@pytest.mark.django_db
def test_add_member_to_closed_pmo_409(admin_auth, emp):
    pmo = _pmo(status="closed")
    resp = Client().post(
        f"{BASE}/{pmo.id}/members", data={"employee_id": emp.id},
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 409
    assert resp.json()["detail"] == "Cannot add members to a closed PMO"


@pytest.mark.django_db
def test_add_member_invalid_dates_422(admin_auth, emp):
    pmo = _pmo()
    resp = Client().post(
        f"{BASE}/{pmo.id}/members",
        data={
            "employee_id": emp.id,
            "from_date": TODAY.isoformat(),
            "to_date": (TODAY - datetime.timedelta(days=1)).isoformat(),
        },
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 422


@pytest.mark.django_db
def test_add_member_duplicate_active_409(admin_auth, emp):
    pmo = _pmo()
    _member(pmo, emp)
    resp = Client().post(
        f"{BASE}/{pmo.id}/members", data={"employee_id": emp.id},
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 409
    assert resp.json()["detail"] == "Employee is already an active member of this PMO"


@pytest.mark.django_db
def test_add_second_active_primary_409(admin_auth, emp, emp2):
    """Порт test_second_active_primary_returns_409 исходника."""
    pmo = _pmo()
    r1 = Client().post(
        f"{BASE}/{pmo.id}/members", data={"employee_id": emp.id, "is_primary": True},
        content_type="application/json", **admin_auth,
    )
    assert r1.status_code == 201

    r2 = Client().post(
        f"{BASE}/{pmo.id}/members", data={"employee_id": emp2.id, "is_primary": True},
        content_type="application/json", **admin_auth,
    )
    assert r2.status_code == 409
    assert r2.json()["detail"] == "PMO already has a primary member"


@pytest.mark.django_db
def test_closed_primary_allows_new_primary(admin_auth, emp, emp2):
    """Порт test_closed_primary_allows_new_primary исходника."""
    pmo = _pmo()
    created = Client().post(
        f"{BASE}/{pmo.id}/members",
        data={"employee_id": emp.id, "is_primary": True,
              "from_date": (TODAY - datetime.timedelta(days=2)).isoformat()},
        content_type="application/json", **admin_auth,
    )
    assert created.status_code == 201
    member_id = created.json()["id"]

    closed = Client().patch(
        f"{BASE}/{pmo.id}/members/{member_id}",
        data={"to_date": (TODAY - datetime.timedelta(days=1)).isoformat()},
        content_type="application/json", **admin_auth,
    )
    assert closed.status_code == 200

    next_primary = Client().post(
        f"{BASE}/{pmo.id}/members", data={"employee_id": emp2.id, "is_primary": True},
        content_type="application/json", **admin_auth,
    )
    assert next_primary.status_code == 201


@pytest.mark.django_db
def test_overallocation_returns_warning_header_without_blocking(admin_auth, emp):
    """Порт test_overallocation_returns_warning_header_without_blocking исходника."""
    pmo1 = _pmo(name="P1", code="P1")
    pmo2 = _pmo(name="P2", code="P2")

    first = Client().post(
        f"{BASE}/{pmo1.id}/members", data={"employee_id": emp.id, "allocation_percent": 60},
        content_type="application/json", **admin_auth,
    )
    assert first.status_code == 201

    second = Client().post(
        f"{BASE}/{pmo2.id}/members", data={"employee_id": emp.id, "allocation_percent": 50},
        content_type="application/json", **admin_auth,
    )
    assert second.status_code == 201
    assert second.headers["X-Allocation-Warning"] == "110"


# ── /pmo/{id}/members/{member_id} ────────────────────────────────────────

@pytest.mark.django_db
def test_update_member_not_found_404(admin_auth, emp):
    pmo = _pmo()
    member = _member(pmo, emp)
    other_pmo = _pmo(name="Other", code="OTHER")
    resp = Client().patch(
        f"{BASE}/{other_pmo.id}/members/{member.id}", data={"allocation_percent": 50},
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Member not found in this PMO"


@pytest.mark.django_db
def test_update_member_patches_only_provided_fields(admin_auth, emp):
    """exclude_unset — поля, не присланные клиентом, не затираются."""
    pmo = _pmo()
    member = _member(pmo, emp, position_in_pmo="Old", allocation_percent=30)

    resp = Client().patch(
        f"{BASE}/{pmo.id}/members/{member.id}", data={"allocation_percent": 55},
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 200
    assert resp.json()["allocation_percent"] == 55
    assert resp.json()["position_in_pmo"] == "Old"


@pytest.mark.django_db
def test_remove_member_soft_closes(admin_auth, emp):
    pmo = _pmo()
    member = _member(pmo, emp)

    resp = Client().delete(f"{BASE}/{pmo.id}/members/{member.id}", **admin_auth)
    assert resp.status_code == 204
    member.refresh_from_db()
    assert member.to_date == TODAY
    assert PMOMember.objects.filter(id=member.id).exists()  # НЕ физическое удаление


@pytest.mark.django_db
def test_remove_member_not_found_404(admin_auth):
    pmo = _pmo()
    resp = Client().delete(f"{BASE}/{pmo.id}/members/999999", **admin_auth)
    assert resp.status_code == 404


# ── /pmo/{id}/org-chart ───────────────────────────────────────────────────

@pytest.mark.django_db
def test_org_chart_shape(auth, emp):
    pmo = _pmo()
    _member(pmo, emp, position_in_pmo="Lead", is_primary=True)

    resp = Client().get(f"{BASE}/{pmo.id}/org-chart", **auth)
    assert resp.status_code == 200
    body = resp.json()
    assert body["nodes"][0] == {
        "id": f"pmo_{pmo.id}", "label": "PMO Alpha", "type": "pmo", "unit_type": "pmo",
        "level": None, "weight": None, "meta": {"code": "ALPHA", "status": "active"},
    }
    emp_node = next(n for n in body["nodes"] if n["type"] == "employee")
    assert emp_node["id"] == f"emp_{emp.id}"
    assert emp_node["meta"]["position_title"] == "Lead"
    assert {"source": f"pmo_{pmo.id}", "target": f"emp_{emp.id}", "relation_type": "permanent"} in body["edges"]


@pytest.mark.django_db
def test_org_chart_404_for_missing_pmo(auth):
    assert Client().get(f"{BASE}/999999/org-chart", **auth).status_code == 404


# ── GET /employees/{id}/pmos, /employees/me/pmos — сквозной end-to-end ──────
#
# Юнит-детали (auth/scoping/shape) — в test_employees_api.py; здесь — только
# доказательство, что pmo_service используется по-настоящему обоими путями
# входа (POST /pmo/{id}/members и GET /employees/{id}/pmos видят одни и те
# же данные).

@pytest.mark.django_db
def test_employee_pmos_endpoint_reflects_pmo_membership(admin_auth, emp):
    pmo = _pmo()
    Client().post(
        f"{BASE}/{pmo.id}/members", data={"employee_id": emp.id},
        content_type="application/json", **admin_auth,
    )
    resp = Client().get(f"{EBASE}/{emp.id}/pmos", **admin_auth)
    assert resp.status_code == 200
    [item] = resp.json()
    assert item["pmo_id"] == pmo.id
