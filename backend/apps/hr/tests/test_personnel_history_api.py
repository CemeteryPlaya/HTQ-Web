"""Контракт /api/hr/v1/personnel-history/* — паритет с
services/hr/app/api/v1/personnel_history.py.

Логика была inline в роутере исходника (нет отдельного personnel_history_
service.py) — здесь вынесена в apps/hr/services/personnel_history_service.py
по конвенции остальных под-модулей аппки.

Авторизация: reads = get_current_user исходника -> auth="jwt"; writes =
require_hr_write исходника (is_elevated) -> api_view(admin=True) — та же пара,
что у departments/positions/org.

Зафиксированные ловушки паритета (проверяются тестами ниже):
  * список отдаёт ГОЛЫЙ массив (НЕ paginated envelope), order_by=(event_date
    desc, id desc);
  * ответ несёт резолвленные display-имена (employee_name,
    *_department_name, *_position_title), created_by_name всегда null
    (буквальный порт — "нет employee_replica в hr-сервисе");
  * event_type вне EVENT_TYPES -> 400 (НЕ 422 — контракт исходника, ручной
    HTTPException(400) в роутере, не pydantic-валидация);
  * PUT — единственный метод записи детального ресурса (исходник не
    регистрирует PATCH, фронт (HRHistory.tsx) шлёт только PUT — нет живого
    мисматча, PATCH не регистрируем);
  * create/update не пре-валидируют существование employee/from_*/to_* —
    несуществующий employee роняет IntegrityError необработанным (500,
    контракт, не баг).

План: docs/plans/2026-07-20-hr-domain.md
"""
from __future__ import annotations

import datetime

import pytest
from django.test import Client

from apps.hr.models import Department, Employee, PersonnelHistory, Position
from apps.users.models import User, UserStatus
from htqweb.authn.jwt import issue_token_pair

BASE = "/api/hr/v1/personnel-history"


@pytest.fixture
def dep(db):
    return Department.objects.create(name="ИТ", path="it")


@pytest.fixture
def other_dep(db):
    return Department.objects.create(name="Финансы", path="fin")


@pytest.fixture
def pos(db, dep):
    return Position.objects.create(title="Инженер", department=dep, weight=100)


@pytest.fixture
def emp(db, dep, pos):
    return Employee.objects.create(
        first_name="Иван", last_name="Иванов", email="ivan@htq.test", department=dep, position=pos,
        hire_date=datetime.date(2024, 1, 9),
    )


@pytest.fixture
def auth(db):
    user = User.objects.create(
        username="ph-user", email="ph-user@htq.test", password="x", status=UserStatus.ACTIVE,
    )
    user.set_password("S3cret!Pass1")
    user.save()
    return {"HTTP_AUTHORIZATION": f"Bearer {issue_token_pair(user)['access']}"}


@pytest.fixture
def admin_auth(db):
    user = User.objects.create(
        username="ph-admin", email="ph-admin@htq.test", password="x", status=UserStatus.ACTIVE,
        is_staff=True,
    )
    user.set_password("Adm1n!Pass")
    user.save()
    return {"HTTP_AUTHORIZATION": f"Bearer {issue_token_pair(user)['access']}"}


def _hist(emp, event_type="hired", event_date=datetime.date(2026, 1, 1), **kw):
    return PersonnelHistory.objects.create(
        employee=emp, event_type=event_type, event_date=event_date, **kw,
    )


# ── auth ──────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_requires_jwt_on_list():
    assert Client().get(f"{BASE}/").status_code == 401


@pytest.mark.django_db
def test_read_allowed_for_plain_jwt_user(auth, emp):
    _hist(emp)
    resp = Client().get(f"{BASE}/", **auth)
    assert resp.status_code == 200


@pytest.mark.django_db
def test_create_forbidden_for_non_admin(auth, emp):
    resp = Client().post(
        f"{BASE}/", data={"employee": emp.id, "event_date": "2026-01-01"},
        content_type="application/json", **auth,
    )
    assert resp.status_code == 403


# ── GET / — bare array, ordered event_date desc, id desc ────────────────────

@pytest.mark.django_db
def test_list_returns_bare_array_ordered_by_event_date_desc(admin_auth, emp):
    _hist(emp, event_date=datetime.date(2026, 1, 1))
    _hist(emp, event_date=datetime.date(2026, 3, 1))
    _hist(emp, event_date=datetime.date(2026, 2, 1))

    resp = Client().get(f"{BASE}/", **admin_auth)
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    assert [r["event_date"] for r in body] == ["2026-03-01", "2026-02-01", "2026-01-01"]


@pytest.mark.django_db
def test_list_resolves_display_names(admin_auth, emp, dep, other_dep, pos):
    other_pos = Position.objects.create(title="Ст. инженер", department=other_dep, weight=50)
    _hist(
        emp, event_type="transfer", from_department=dep, to_department=other_dep,
        from_position=pos, to_position=other_pos, order_number="123", comment="c",
    )
    resp = Client().get(f"{BASE}/", **admin_auth)
    row = resp.json()[0]
    assert row["employee"] == emp.id
    assert row["employee_name"] == "Иванов Иван"
    assert row["from_department_name"] == "ИТ"
    assert row["to_department_name"] == "Финансы"
    assert row["from_position_title"] == "Инженер"
    assert row["to_position_title"] == "Ст. инженер"
    assert row["order_number"] == "123"
    assert row["comment"] == "c"
    assert row["created_by_name"] is None
    assert set(row) == {
        "id", "employee", "employee_name", "event_type", "event_date",
        "from_department", "from_department_name", "to_department", "to_department_name",
        "from_position", "from_position_title", "to_position", "to_position_title",
        "order_number", "comment", "created_by_name", "created_at",
    }


@pytest.mark.django_db
def test_list_null_department_position_resolve_to_none(admin_auth, emp):
    _hist(emp, event_type="hired")
    row = Client().get(f"{BASE}/", **admin_auth).json()[0]
    assert row["from_department"] is None
    assert row["from_department_name"] is None
    assert row["to_position"] is None
    assert row["to_position_title"] is None


# ── POST / — create ───────────────────────────────────────────────────────

@pytest.mark.django_db
def test_create_201(admin_auth, emp):
    resp = Client().post(
        f"{BASE}/",
        data={"employee": emp.id, "event_type": "hired", "event_date": "2026-01-01",
              "order_number": "A-1", "comment": "welcome"},
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["event_type"] == "hired"
    assert body["order_number"] == "A-1"
    assert PersonnelHistory.objects.filter(employee=emp).count() == 1


@pytest.mark.django_db
def test_create_records_created_by_from_token(admin_auth, emp):
    resp = Client().post(
        f"{BASE}/", data={"employee": emp.id, "event_date": "2026-01-01"},
        content_type="application/json", **admin_auth,
    )
    ph = PersonnelHistory.objects.get(id=resp.json()["id"])
    assert ph.created_by is not None


@pytest.mark.django_db
def test_create_defaults_event_type_to_other(admin_auth, emp):
    resp = Client().post(
        f"{BASE}/", data={"employee": emp.id, "event_date": "2026-01-01"},
        content_type="application/json", **admin_auth,
    )
    assert resp.json()["event_type"] == "other"


@pytest.mark.django_db
def test_create_invalid_event_type_400_not_422(admin_auth, emp):
    resp = Client().post(
        f"{BASE}/", data={"employee": emp.id, "event_type": "bogus", "event_date": "2026-01-01"},
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 400
    assert "event_type must be one of" in resp.json()["detail"]


# create_history/update_history НЕ пре-валидируют существование employee/
# from_*/to_* (контракт, не баг — см. модульный докстринг сервиса и роутер
# исходника: никакого HTTPException до insert). Не покрыто интеграционным
# тестом здесь: Django создаёт FK-констрейнты на Postgres как DEFERRABLE
# INITIALLY DEFERRED (проверено эмпирически — pg_constraint.condeferred=true
# для hr_personnelhistory_employee_id_...), а pytest-django оборачивает
# каждый тест в SAVEPOINT — нарушение всплывает только на teardown
# ("SET CONSTRAINTS ALL IMMEDIATE"), НЕ в момент запроса, поэтому статус-код
# ответа в тесте недостоверен (в проде без внешнего atomic() — обычный
# autocommit одной INSERT-инструкции — упало бы синхронно тем же 500, что и
# у TimeEntry-дубликата выше, который проверяем: ограничение там UNIQUE, а
# не FOREIGN KEY, и Django не делает UNIQUE-констрейнты deferred).


# ── PUT /{id}/ — update ───────────────────────────────────────────────────

@pytest.mark.django_db
def test_update_200(admin_auth, emp):
    hist = _hist(emp, event_type="hired")
    resp = Client().put(
        f"{BASE}/{hist.id}/",
        data={"employee": emp.id, "event_type": "promotion", "event_date": "2026-05-01", "comment": "up"},
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 200
    assert resp.json()["event_type"] == "promotion"
    hist.refresh_from_db()
    assert hist.event_type == "promotion"
    assert hist.comment == "up"


@pytest.mark.django_db
def test_update_not_found_404(admin_auth, emp):
    resp = Client().put(
        f"{BASE}/999999/", data={"employee": emp.id, "event_date": "2026-01-01"},
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "PersonnelHistory not found"


@pytest.mark.django_db
def test_update_invalid_event_type_400(admin_auth, emp):
    hist = _hist(emp)
    resp = Client().put(
        f"{BASE}/{hist.id}/", data={"employee": emp.id, "event_type": "nope", "event_date": "2026-01-01"},
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 400


@pytest.mark.django_db
def test_update_forbidden_for_non_admin(auth, emp):
    hist = _hist(emp)
    resp = Client().put(
        f"{BASE}/{hist.id}/", data={"employee": emp.id, "event_date": "2026-01-01"},
        content_type="application/json", **auth,
    )
    assert resp.status_code == 403


# ── DELETE /{id}/ ─────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_delete_204(admin_auth, emp):
    hist = _hist(emp)
    resp = Client().delete(f"{BASE}/{hist.id}/", **admin_auth)
    assert resp.status_code == 204
    assert not PersonnelHistory.objects.filter(id=hist.id).exists()


@pytest.mark.django_db
def test_delete_not_found_404(admin_auth):
    resp = Client().delete(f"{BASE}/999999/", **admin_auth)
    assert resp.status_code == 404


@pytest.mark.django_db
def test_delete_forbidden_for_non_admin(auth, emp):
    hist = _hist(emp)
    resp = Client().delete(f"{BASE}/{hist.id}/", **auth)
    assert resp.status_code == 403


# ── FK on_delete: from/to department/position -> SET_NULL; employee -> CASCADE ─

@pytest.mark.django_db
def test_deleting_department_nulls_out_reference_not_cascades(admin_auth, emp, other_dep):
    # other_dep — НЕ отдел самого emp (тот PROTECTed через Employee.department)
    # — свободно удаляем, чтобы проверить SET_NULL именно на personnel_history.
    hist = _hist(emp, from_department=other_dep)
    other_dep.delete()
    hist.refresh_from_db()
    assert hist.from_department_id is None


@pytest.mark.django_db
def test_deleting_employee_cascades_history(db, emp):
    _hist(emp)
    emp.delete()
    assert PersonnelHistory.objects.count() == 0
