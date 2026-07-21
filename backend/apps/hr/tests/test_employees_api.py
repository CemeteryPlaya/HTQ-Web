"""Контракт /api/hr/v1/employees/* — паритет с services/hr/app/api/v1/employees.py.

Провенанс формы ответов: app/schemas/employee.py (EmployeeOut), поведение —
app/services/employee_service.py + app/auth/hr_access.py.

10 из 16 эндпойнтов исходника перенесены сейчас (документы — hr-docs, задача
5 плана, см. test_documents_api.py); 6 отложены (users/, pmos, card — их
зависимости в hr-misc/apps.users.interface ещё не перенесены) — растяжки
внизу файла следят за появлением зависимостей.

Зафиксированные ловушки паритета (проверяются тестами ниже):
  * авторизация — ТОНКАЯ роль внутри вьюх (resolve_hr_access + access.can_*),
    а не грубый api_view(admin=True): elevated JWT (is_admin/is_staff/
    is_superuser) -> HRAccess(level="lead", permissions={"*"}); иначе роль
    считается из Employee.position (title/department эвристика или явный
    permissions.hr_level);
  * скрытый отдел на detail-эндпойнтах -> 404 "Employee not found" (НЕ 403) —
    намеренная приватность;
  * список без прав на "видеть всё" скоупится на свой отдел, а при чужом
    department_id в query отдаёт ПУСТУЮ страницу (total=0, pages=0), а не 404;
  * PUT + PATCH оба работают на /{id}/;
  * смена department_id/position_id/termination_date или перевод в
    terminated|suspended|rejected требует can_transfer_employee — иначе 403 с
    точным detail исходника;
  * DELETE — мягкое удаление (is_deleted=True И status='terminated' — ОБЕ
    колонки, не только is_deleted);
  * /me/ отдаёт профиль БЕЗ фильтра is_deleted (мягко удалённый видит себя);
  * transfer игнорирует effective_date (буквальное поведение исходника);
  * все мутации пишут запись в hr_auditlog (create/update/delete), history
    отдаёт последние 100 записей по entity_type="employee" desc.

План: docs/plans/2026-07-20-hr-domain.md
"""
from __future__ import annotations

import datetime

import pytest
from django.test import Client

from apps.hr.models import AuditLog, Department, Employee, Position
from apps.users.models import User, UserStatus
from htqweb.authn.jwt import issue_token_pair

BASE = "/api/hr/v1/employees"


def _dep(name, path, **kw):
    return Department.objects.create(name=name, path=path, **kw)


def _pos(title, dep, weight, **kw):
    return Position.objects.create(title=title, department=dep, weight=weight, **kw)


def _emp(dep, pos, email, **kw):
    kw.setdefault("hire_date", datetime.date(2024, 1, 9))
    kw.setdefault("first_name", "И")
    kw.setdefault("last_name", "И")
    return Employee.objects.create(email=email, department=dep, position=pos, **kw)


def _user_auth(email, *, is_staff=False):
    user = User.objects.create(
        username=email.split("@")[0], email=email, password="x", status=UserStatus.ACTIVE,
        is_staff=is_staff,
    )
    user.set_password("S3cret!Pass1")
    user.save()
    return user, {"HTTP_AUTHORIZATION": f"Bearer {issue_token_pair(user)['access']}"}


@pytest.fixture
def hr_dep(db):
    return _dep("HR", "hr")


@pytest.fixture
def other_dep(db):
    return _dep("Финансы", "fin")


@pytest.fixture
def auth(db):
    """Обычный вошедший без Employee-профиля — нет HR-доступа вообще."""
    _user, headers = _user_auth("plain@htq.test")
    return headers


@pytest.fixture
def admin_auth(db):
    """is_staff=True — elevated -> HRAccess(level='lead', permissions={'*'})."""
    _user, headers = _user_auth("hr-admin@htq.test", is_staff=True)
    return headers


@pytest.fixture
def junior(db, hr_dep):
    pos = _pos("HR Assistant", hr_dep, weight=10)
    user, headers = _user_auth("hr-junior@htq.test")
    emp = _emp(hr_dep, pos, "hr-junior@htq.test", user_id=user.id)
    return emp, headers


@pytest.fixture
def middle(db, hr_dep):
    pos = _pos("HR Manager", hr_dep, weight=20)
    user, headers = _user_auth("hr-middle@htq.test")
    emp = _emp(hr_dep, pos, "hr-middle@htq.test", user_id=user.id)
    return emp, headers


@pytest.fixture
def senior(db, hr_dep):
    pos = _pos("Senior HR Manager", hr_dep, weight=30)
    user, headers = _user_auth("hr-senior@htq.test")
    emp = _emp(hr_dep, pos, "hr-senior@htq.test", user_id=user.id)
    return emp, headers


@pytest.fixture
def lead(db, hr_dep):
    pos = _pos("HR Director", hr_dep, weight=40)
    user, headers = _user_auth("hr-lead@htq.test")
    emp = _emp(hr_dep, pos, "hr-lead@htq.test", user_id=user.id)
    return emp, headers


# ── auth ────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_requires_jwt_on_list():
    assert Client().get(f"{BASE}/").status_code == 401


@pytest.mark.django_db
def test_requires_jwt_on_hr_level():
    assert Client().get(f"{BASE}/hr-level/").status_code == 401


# ── GET /hr-level/ ────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_hr_level_null_for_user_without_employee_profile(auth):
    resp = Client().get(f"{BASE}/hr-level/", **auth)
    assert resp.status_code == 200
    body = resp.json()
    assert body["level"] is None
    assert body["permissions"] == []
    assert body["can_read_all"] is False
    assert body["can_create_employee"] is False


@pytest.mark.django_db
def test_hr_level_elevated_admin_is_lead_wildcard(admin_auth):
    body = Client().get(f"{BASE}/hr-level/", **admin_auth).json()
    assert body["level"] == "lead"
    assert body["permissions"] == ["*"]
    assert body["can_read_all"] is True
    assert body["can_delete_employee"] is True
    assert body["scope_department_id"] is None


@pytest.mark.django_db
def test_hr_level_reflects_employee_role(senior):
    _owner, headers = senior
    body = Client().get(f"{BASE}/hr-level/", **headers).json()
    assert body["level"] == "senior"
    assert body["can_read_all"] is True
    assert body["can_create_employee"] is True
    assert body["can_delete_employee"] is False
    assert "hr.employees.view" in body["permissions"]


# ── GET /me/ ──────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_me_404_when_no_employee_profile(auth):
    resp = Client().get(f"{BASE}/me/", **auth)
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Employee profile not found"


@pytest.mark.django_db
def test_me_returns_own_employee_by_user_id(junior):
    emp, headers = junior
    body = Client().get(f"{BASE}/me/", **headers).json()
    assert body["id"] == emp.id
    assert body["email"] == emp.email
    assert body["department"]["id"] == emp.department_id
    assert body["position"]["id"] == emp.position_id


@pytest.mark.django_db
def test_me_falls_back_to_email_match(hr_dep):
    pos = _pos("HR Assistant", hr_dep, weight=11)
    user, headers = _user_auth("legacy@htq.test")
    emp = _emp(hr_dep, pos, "legacy@htq.test", user_id=None)  # legacy row, no user_id
    body = Client().get(f"{BASE}/me/", **headers).json()
    assert body["id"] == emp.id


@pytest.mark.django_db
def test_me_includes_soft_deleted_employee(junior):
    """Оддость исходника: /me/ НЕ фильтрует is_deleted — мягко удалённый
    (уволенный) видит собственную анкету."""
    emp, headers = junior
    emp.is_deleted = True
    emp.save(update_fields=["is_deleted"])
    resp = Client().get(f"{BASE}/me/", **headers)
    assert resp.status_code == 200
    assert resp.json()["id"] == emp.id


# ── GET / (list) ────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_list_forbidden_without_any_hr_access(auth):
    resp = Client().get(f"{BASE}/", **auth)
    assert resp.status_code == 403
    assert resp.json()["detail"] == "HR access required"


@pytest.mark.django_db
def test_list_scoped_to_own_department(middle, other_dep):
    emp, headers = middle
    other_pos = _pos("Инженер", other_dep, weight=500)
    _emp(other_dep, other_pos, "outsider@htq.test")

    body = Client().get(f"{BASE}/", **headers).json()
    assert {i["id"] for i in body["items"]} == {emp.id}
    assert body["total"] == 1


@pytest.mark.django_db
def test_list_returns_empty_page_for_foreign_department_query(middle, other_dep):
    _owner, headers = middle
    resp = Client().get(f"{BASE}/?department_id={other_dep.id}", **headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"items": [], "total": 0, "page": 1, "pages": 0, "limit": 20}


@pytest.mark.django_db
def test_list_admin_sees_all_departments_paginated(admin_auth, hr_dep, other_dep):
    for i in range(3):
        _emp(hr_dep, _pos(f"P{i}", hr_dep, weight=100 + i), f"p{i}@htq.test")
    _emp(other_dep, _pos("Q0", other_dep, weight=200), "q0@htq.test")

    resp = Client().get(f"{BASE}/?page=1&limit=2", **admin_auth)
    body = resp.json()
    assert body["total"] == 4
    assert body["pages"] == 2
    assert len(body["items"]) == 2


@pytest.mark.django_db
def test_list_filters_by_status_and_search(admin_auth, hr_dep):
    _emp(hr_dep, _pos("A", hr_dep, weight=100), "ivanov@htq.test",
         first_name="Иван", last_name="Иванов", status="active")
    _emp(hr_dep, _pos("B", hr_dep, weight=101), "petrov@htq.test",
         first_name="Пётр", last_name="Петров", status="inactive")

    resp = Client().get(f"{BASE}/?status=inactive", **admin_auth)
    assert [i["email"] for i in resp.json()["items"]] == ["petrov@htq.test"]

    resp2 = Client().get(f"{BASE}/?search=Иванов", **admin_auth)
    assert [i["email"] for i in resp2.json()["items"]] == ["ivanov@htq.test"]


@pytest.mark.django_db
def test_list_invalid_query_params_422(admin_auth):
    assert Client().get(f"{BASE}/?page=0", **admin_auth).status_code == 422
    assert Client().get(f"{BASE}/?limit=500", **admin_auth).status_code == 422


# ── POST / (create) ───────────────────────────────────────────────────────

def _create_payload(dep, pos, email="new@htq.test"):
    return {
        "first_name": "Новый", "last_name": "Сотрудник", "email": email,
        "department_id": dep.id, "position_id": pos.id, "hire_date": "2026-01-15",
    }


@pytest.mark.django_db
def test_create_requires_jwt():
    resp = Client().post(f"{BASE}/", data={}, content_type="application/json")
    assert resp.status_code == 401


@pytest.mark.django_db
def test_create_forbidden_without_any_hr_access(auth, hr_dep):
    pos = _pos("Инженер", hr_dep, weight=100)
    resp = Client().post(
        f"{BASE}/", data=_create_payload(hr_dep, pos), content_type="application/json", **auth,
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "HR access required"


@pytest.mark.django_db
def test_create_forbidden_for_middle_level(middle, hr_dep):
    _owner, headers = middle
    pos = _pos("Инженер", hr_dep, weight=101)
    resp = Client().post(
        f"{BASE}/", data=_create_payload(hr_dep, pos), content_type="application/json", **headers,
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Senior HR access required"


@pytest.mark.django_db
def test_create_succeeds_for_senior(senior, hr_dep):
    _owner, headers = senior
    pos = _pos("Инженер", hr_dep, weight=102)
    resp = Client().post(
        f"{BASE}/", data=_create_payload(hr_dep, pos), content_type="application/json", **headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["email"] == "new@htq.test"
    assert body["status"] == "active"
    assert body["department"]["id"] == hr_dep.id


@pytest.mark.django_db
def test_create_writes_audit_log_entry(admin_auth, hr_dep):
    pos = _pos("Инженер", hr_dep, weight=103)
    resp = Client().post(
        f"{BASE}/", data=_create_payload(hr_dep, pos), content_type="application/json", **admin_auth,
    )
    emp_id = resp.json()["id"]
    log = AuditLog.objects.get(entity_type="employee", entity_id=emp_id, action="create")
    assert log.new_values["email"] == "new@htq.test"
    assert log.old_values is None


@pytest.mark.django_db
def test_create_department_not_found_422(admin_auth, hr_dep):
    pos = _pos("Инженер", hr_dep, weight=104)
    payload = _create_payload(hr_dep, pos)
    payload["department_id"] = 999_999
    resp = Client().post(f"{BASE}/", data=payload, content_type="application/json", **admin_auth)
    assert resp.status_code == 422
    assert resp.json()["detail"] == "Department not found"


@pytest.mark.django_db
def test_create_position_not_found_422(admin_auth, hr_dep):
    pos = _pos("Инженер", hr_dep, weight=105)
    payload = _create_payload(hr_dep, pos)
    payload["position_id"] = 999_999
    resp = Client().post(f"{BASE}/", data=payload, content_type="application/json", **admin_auth)
    assert resp.status_code == 422
    assert resp.json()["detail"] == "Position not found"


@pytest.mark.django_db
def test_create_duplicate_email_409(admin_auth, hr_dep):
    pos = _pos("Инженер", hr_dep, weight=106)
    _emp(hr_dep, pos, "dup@htq.test")
    resp = Client().post(
        f"{BASE}/", data=_create_payload(hr_dep, pos, email="dup@htq.test"),
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 409
    assert resp.json()["detail"] == "Email already in use"


# ── GET /{id}/ ──────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_get_forbidden_without_any_hr_access(auth, hr_dep):
    pos = _pos("Инженер", hr_dep, weight=110)
    target = _emp(hr_dep, pos, "target@htq.test")
    resp = Client().get(f"{BASE}/{target.id}/", **auth)
    assert resp.status_code == 403
    assert resp.json()["detail"] == "HR access required"


@pytest.mark.django_db
def test_get_visible_within_own_department(middle, hr_dep):
    emp, headers = middle
    resp = Client().get(f"{BASE}/{emp.id}/", **headers)
    assert resp.status_code == 200
    assert resp.json()["id"] == emp.id


@pytest.mark.django_db
def test_get_other_department_returns_404_not_403(middle, other_dep):
    _owner, headers = middle
    outsider = _emp(other_dep, _pos("Инженер", other_dep, weight=520), "outsider2@htq.test")
    resp = Client().get(f"{BASE}/{outsider.id}/", **headers)
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Employee not found"


@pytest.mark.django_db
def test_get_missing_employee_404(admin_auth):
    resp = Client().get(f"{BASE}/999999/", **admin_auth)
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Employee not found"


@pytest.mark.django_db
def test_get_admin_sees_any_department(admin_auth, other_dep):
    outsider = _emp(other_dep, _pos("Инженер", other_dep, weight=530), "outsider3@htq.test")
    resp = Client().get(f"{BASE}/{outsider.id}/", **admin_auth)
    assert resp.status_code == 200


# ── PUT + PATCH /{id}/ ────────────────────────────────────────────────────

@pytest.mark.django_db
@pytest.mark.parametrize("method", ["put", "patch"])
def test_update_accepts_both_put_and_patch(admin_auth, hr_dep, method):
    target = _emp(hr_dep, _pos("Инженер", hr_dep, weight=140), "up@htq.test")
    resp = getattr(Client(), method)(
        f"{BASE}/{target.id}/", data={"first_name": "Изменённое"},
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 200
    assert resp.json()["first_name"] == "Изменённое"
    target.refresh_from_db()
    assert target.first_name == "Изменённое"


@pytest.mark.django_db
def test_update_forbidden_without_any_hr_access(auth, hr_dep):
    target = _emp(hr_dep, _pos("Инженер", hr_dep, weight=141), "up2@htq.test")
    resp = Client().patch(
        f"{BASE}/{target.id}/", data={"first_name": "X"}, content_type="application/json", **auth,
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "HR access required"


@pytest.mark.django_db
def test_update_forbidden_for_junior_write_access(junior):
    emp, headers = junior
    resp = Client().patch(
        f"{BASE}/{emp.id}/", data={"first_name": "X"}, content_type="application/json", **headers,
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "HR write access required"


@pytest.mark.django_db
def test_update_other_department_returns_404(middle, other_dep):
    _owner, headers = middle
    outsider = _emp(other_dep, _pos("Инженер", other_dep, weight=542), "outsider4@htq.test")
    resp = Client().patch(
        f"{BASE}/{outsider.id}/", data={"first_name": "X"}, content_type="application/json", **headers,
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Employee not found"


@pytest.mark.django_db
def test_update_ignores_none_fields(admin_auth, hr_dep):
    target = _emp(hr_dep, _pos("Инженер", hr_dep, weight=143), "up3@htq.test", bio="исходное")
    Client().patch(
        f"{BASE}/{target.id}/", data={"first_name": "Обновлён", "bio": None},
        content_type="application/json", **admin_auth,
    )
    target.refresh_from_db()
    assert target.first_name == "Обновлён"
    assert target.bio == "исходное"  # exclude_none в исходнике


@pytest.mark.django_db
def test_update_restricted_field_requires_transfer_permission(middle, other_dep):
    emp, headers = middle
    resp = Client().patch(
        f"{BASE}/{emp.id}/", data={"department_id": other_dep.id},
        content_type="application/json", **headers,
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == (
        "Transferring, changing position, or terminating requires the transfer permission"
    )


@pytest.mark.django_db
def test_update_status_to_terminated_requires_transfer_permission(middle):
    emp, headers = middle
    resp = Client().patch(
        f"{BASE}/{emp.id}/", data={"status": "terminated"},
        content_type="application/json", **headers,
    )
    assert resp.status_code == 403


@pytest.mark.django_db
def test_update_restricted_field_succeeds_for_senior(senior, hr_dep):
    emp, headers = senior
    other_pos = _pos("Другая должность", hr_dep, weight=560)
    resp = Client().patch(
        f"{BASE}/{emp.id}/", data={"position_id": other_pos.id},
        content_type="application/json", **headers,
    )
    assert resp.status_code == 200
    assert resp.json()["position"]["id"] == other_pos.id


@pytest.mark.django_db
def test_update_duplicate_email_409(admin_auth, hr_dep):
    _emp(hr_dep, _pos("A", hr_dep, weight=144), "taken@htq.test")
    target = _emp(hr_dep, _pos("B", hr_dep, weight=145), "free@htq.test")
    resp = Client().patch(
        f"{BASE}/{target.id}/", data={"email": "taken@htq.test"},
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 409


@pytest.mark.django_db
def test_update_department_not_found_422(admin_auth, hr_dep):
    target = _emp(hr_dep, _pos("A", hr_dep, weight=146), "e1@htq.test")
    resp = Client().patch(
        f"{BASE}/{target.id}/", data={"department_id": 999_999},
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 422


@pytest.mark.django_db
def test_update_writes_audit_log_entry(admin_auth, hr_dep):
    target = _emp(hr_dep, _pos("A", hr_dep, weight=147), "e2@htq.test")
    Client().patch(
        f"{BASE}/{target.id}/", data={"first_name": "Аудит"},
        content_type="application/json", **admin_auth,
    )
    log = AuditLog.objects.get(entity_type="employee", entity_id=target.id, action="update")
    assert log.new_values["first_name"] == "Аудит"


# ── DELETE /{id}/ ───────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_delete_forbidden_without_any_hr_access(auth, hr_dep):
    target = _emp(hr_dep, _pos("A", hr_dep, weight=150), "d1@htq.test")
    resp = Client().delete(f"{BASE}/{target.id}/", **auth)
    assert resp.status_code == 403
    assert resp.json()["detail"] == "HR access required"


@pytest.mark.django_db
def test_delete_forbidden_for_senior_lacks_co_access(senior):
    emp, headers = senior
    resp = Client().delete(f"{BASE}/{emp.id}/", **headers)
    assert resp.status_code == 403
    assert resp.json()["detail"] == "CO HR access required"


@pytest.mark.django_db
def test_delete_soft_deletes_and_terminates(admin_auth, hr_dep):
    target = _emp(hr_dep, _pos("A", hr_dep, weight=151), "d2@htq.test")
    resp = Client().delete(f"{BASE}/{target.id}/", **admin_auth)
    assert resp.status_code == 204
    target.refresh_from_db()
    assert target.is_deleted is True
    assert target.status == "terminated"
    # GET после удаления -> 404, т.к. get_employee фильтрует is_deleted
    assert Client().get(f"{BASE}/{target.id}/", **admin_auth).status_code == 404


@pytest.mark.django_db
def test_delete_writes_audit_log_entry(admin_auth, hr_dep):
    target = _emp(hr_dep, _pos("A", hr_dep, weight=152), "d3@htq.test")
    Client().delete(f"{BASE}/{target.id}/", **admin_auth)
    assert AuditLog.objects.filter(
        entity_type="employee", entity_id=target.id, action="delete",
    ).exists()


@pytest.mark.django_db
def test_delete_missing_employee_404(admin_auth):
    resp = Client().delete(f"{BASE}/999999/", **admin_auth)
    assert resp.status_code == 404


# ── POST /{id}/transfer ─────────────────────────────────────────────────────

@pytest.mark.django_db
def test_transfer_forbidden_without_any_hr_access(auth, hr_dep):
    target = _emp(hr_dep, _pos("A", hr_dep, weight=160), "t1@htq.test")
    resp = Client().post(
        f"{BASE}/{target.id}/transfer", data={"department_id": hr_dep.id},
        content_type="application/json", **auth,
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "HR access required"


@pytest.mark.django_db
def test_transfer_forbidden_for_middle_level(middle, other_dep):
    emp, headers = middle
    resp = Client().post(
        f"{BASE}/{emp.id}/transfer", data={"department_id": other_dep.id},
        content_type="application/json", **headers,
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Senior HR access required"


@pytest.mark.django_db
def test_transfer_succeeds_for_senior_and_ignores_effective_date(senior, other_dep):
    emp, headers = senior
    resp = Client().post(
        f"{BASE}/{emp.id}/transfer",
        data={"department_id": other_dep.id, "effective_date": "2030-01-01"},
        content_type="application/json", **headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["department_id"] == other_dep.id
    # effective_date не хранится нигде в EmployeeOut/модели — просто убеждаемся,
    # что запрос не упал и запись обновилась ровно по department_id.
    emp.refresh_from_db()
    assert emp.department_id == other_dep.id


@pytest.mark.django_db
def test_transfer_writes_audit_log_with_old_and_new_department(admin_auth, hr_dep, other_dep):
    target = _emp(hr_dep, _pos("A", hr_dep, weight=161), "t2@htq.test")
    Client().post(
        f"{BASE}/{target.id}/transfer", data={"department_id": other_dep.id},
        content_type="application/json", **admin_auth,
    )
    log = AuditLog.objects.get(entity_type="employee", entity_id=target.id, action="update")
    assert log.old_values == {"department_id": str(hr_dep.id)}
    assert log.new_values == {"department_id": str(other_dep.id)}


@pytest.mark.django_db
def test_transfer_department_not_found_422(admin_auth, hr_dep):
    target = _emp(hr_dep, _pos("A", hr_dep, weight=162), "t3@htq.test")
    resp = Client().post(
        f"{BASE}/{target.id}/transfer", data={"department_id": 999_999},
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 422


@pytest.mark.django_db
def test_transfer_missing_employee_404(admin_auth, hr_dep):
    resp = Client().post(
        f"{BASE}/999999/transfer", data={"department_id": hr_dep.id},
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 404


# ── GET /{id}/history ─────────────────────────────────────────────────────

@pytest.mark.django_db
def test_history_forbidden_without_any_hr_access(auth, hr_dep):
    target = _emp(hr_dep, _pos("A", hr_dep, weight=170), "h1@htq.test")
    resp = Client().get(f"{BASE}/{target.id}/history", **auth)
    assert resp.status_code == 403


@pytest.mark.django_db
def test_history_missing_employee_404(admin_auth):
    resp = Client().get(f"{BASE}/999999/history", **admin_auth)
    assert resp.status_code == 404


@pytest.mark.django_db
def test_history_returns_entries_desc_ordered_with_expected_shape(admin_auth, hr_dep):
    pos = _pos("A", hr_dep, weight=171)
    create_resp = Client().post(
        f"{BASE}/", data=_create_payload(hr_dep, pos, email="hist@htq.test"),
        content_type="application/json", **admin_auth,
    )
    emp_id = create_resp.json()["id"]
    Client().patch(
        f"{BASE}/{emp_id}/", data={"first_name": "Изменён"},
        content_type="application/json", **admin_auth,
    )

    resp = Client().get(f"{BASE}/{emp_id}/history", **admin_auth)
    assert resp.status_code == 200
    body = resp.json()
    assert [entry["action"] for entry in body] == ["update", "create"]
    assert set(body[0]) == {"id", "action", "old_values", "new_values", "changed_by", "created_at"}


@pytest.mark.django_db
def test_history_404_after_soft_delete():
    """_require_visible_employee идёт через get_employee (is_deleted=False) —
    после мягкого удаления история тоже 404, ровно как GET /{id}/ (тот же
    гейт видимости, буквальное поведение исходника)."""
    dep = _dep("HR2", "hr2")
    pos = _pos("A", dep, weight=172)
    target = _emp(dep, pos, "hist2@htq.test")
    _user, headers = _user_auth("hist-admin@htq.test", is_staff=True)
    Client().delete(f"{BASE}/{target.id}/", **headers)
    resp = Client().get(f"{BASE}/{target.id}/history", **headers)
    assert resp.status_code == 404


# ── растяжки: 6 отложенных эндпойнтов ────────────────────────────────────────
#
# Не реализованы — их зависимости ещё не перенесены в apps.hr (модель hr-misc)
# или apps.users.interface (Р3, без S2S). Каждый тест падает ровно в момент
# появления соответствующей зависимости, заставляя дописать эндпойнт — как
# test_cascade_cleanup_todo_is_tracked в test_departments_api.py.

def test_user_options_endpoints_todo_is_tracked():
    """GET/POST /employees/users/ — прокси в user-service в исходнике.

    Р3 (без S2S) требует list_user_options/create_user_option в
    apps.users.interface — это вне зоны apps/hr (её нельзя трогать здесь)."""
    import apps.users.interface as users_interface

    assert not hasattr(users_interface, "list_user_options"), (
        "В apps.users.interface появился list_user_options — допишите "
        "GET/POST /employees/users/ (см. бриф employees, Р3 без S2S) и "
        "снимите эту растяжку"
    )


def test_pmo_endpoints_todo_is_tracked():
    """GET /employees/me/pmos, GET /employees/{id}/pmos — ждут модель PMO
    (под-модуль hr-misc, ещё не перенесён)."""
    from django.apps import apps as django_apps

    existing = {m.__name__ for m in django_apps.get_app_config("hr").get_models()}
    assert "PMO" not in existing, (
        "Появилась модель PMO в apps.hr — допишите GET /employees/me/pmos и "
        "GET /employees/{id}/pmos и снимите эту растяжку"
    )


def test_card_endpoints_todo_is_tracked():
    """GET /employees/me/card, GET /employees/{id}/card — ждут
    EmployeeCard + EmployeeCardService (под-модуль hr-misc, ещё не перенесён)."""
    from django.apps import apps as django_apps

    existing = {m.__name__ for m in django_apps.get_app_config("hr").get_models()}
    assert "EmployeeCard" not in existing, (
        "Появилась модель EmployeeCard в apps.hr — допишите GET "
        "/employees/me/card и GET /employees/{id}/card и снимите эту растяжку"
    )
