"""Контракт /api/hr/v1/employees/* — паритет с services/hr/app/api/v1/employees.py.

Провенанс формы ответов: app/schemas/employee.py (EmployeeOut), поведение —
app/services/employee_service.py + app/auth/hr_access.py.

16 из 16 эндпойнтов исходника перенесены сейчас (документы — hr-docs, задача
5 плана, см. test_documents_api.py; pmos — под-модуль pmo, см. GET /me/pmos
и GET /{id}/pmos ниже; card — под-модуль employee_card, см. GET /me/card и
GET /{id}/card ниже + отдельно test_employee_card_api.py для card/t2 и
card/groups; users/ — GET/POST через apps.users.interface.{list_users_brief,
create_user}, Р3 без S2S, см. блок ниже).

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

from apps.hr.models import AuditLog, Department, Employee, EmployeeCard, PMO, PMOMember, Position
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


# ── GET /me/pmos ─────────────────────────────────────────────────────────────
#
# Порт employees.py::my_pmos исходника (зовёт PMOService.get_employee_pmos) —
# резолвит СВОЙ Employee ровно как /me/ (user_id||email), БЕЗ require_hr_access
# (любой залогиненный с профилем видит собственные PMO-членства).

@pytest.mark.django_db
def test_me_pmos_404_when_no_employee_profile(auth):
    resp = Client().get(f"{BASE}/me/pmos", **auth)
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Employee profile not found"


@pytest.mark.django_db
def test_me_pmos_empty_when_no_memberships(junior):
    _owner, headers = junior
    resp = Client().get(f"{BASE}/me/pmos", **headers)
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.django_db
def test_me_pmos_returns_active_membership_shape(junior):
    emp, headers = junior
    pmo = PMO.objects.create(name="PMO Alpha", code="ALPHA")
    PMOMember.objects.create(
        pmo=pmo, employee=emp, position_in_pmo="Lead", allocation_percent=40,
        is_primary=True, from_date=datetime.date(2024, 1, 1),
    )

    resp = Client().get(f"{BASE}/me/pmos", **headers)
    assert resp.status_code == 200
    [item] = resp.json()
    assert item == {
        "pmo_id": pmo.id, "pmo_name": "PMO Alpha", "pmo_code": "ALPHA",
        "pmo_status": "active", "membership_type": "permanent",
        "position_in_pmo": "Lead", "allocation_percent": 40, "is_primary": True,
        "from_date": "2024-01-01", "to_date": None,
    }


# ── GET /{id}/pmos ────────────────────────────────────────────────────────────
#
# Порт employees.py::employee_pmos исходника — та же пара require_hr_access +
# _require_visible_employee, что и history/documents выше.

@pytest.mark.django_db
def test_id_pmos_forbidden_without_any_hr_access(auth, hr_dep):
    target = _emp(hr_dep, _pos("A", hr_dep, weight=173), "p1@htq.test")
    resp = Client().get(f"{BASE}/{target.id}/pmos", **auth)
    assert resp.status_code == 403


@pytest.mark.django_db
def test_id_pmos_missing_employee_404(admin_auth):
    resp = Client().get(f"{BASE}/999999/pmos", **admin_auth)
    assert resp.status_code == 404


@pytest.mark.django_db
def test_id_pmos_other_department_returns_404_not_403(middle, other_dep):
    _owner, headers = middle
    target = _emp(other_dep, _pos("Other", other_dep, weight=174), "p2@htq.test")
    resp = Client().get(f"{BASE}/{target.id}/pmos", **headers)
    assert resp.status_code == 404


@pytest.mark.django_db
def test_id_pmos_admin_sees_active_membership(admin_auth, hr_dep):
    target = _emp(hr_dep, _pos("A", hr_dep, weight=175), "p3@htq.test")
    pmo = PMO.objects.create(name="PMO Beta", code="BETA")
    PMOMember.objects.create(pmo=pmo, employee=target, from_date=datetime.date(2024, 1, 1))

    resp = Client().get(f"{BASE}/{target.id}/pmos", **admin_auth)
    assert resp.status_code == 200
    [item] = resp.json()
    assert item["pmo_id"] == pmo.id
    assert item["membership_type"] == "permanent"


# ── GET/POST /employees/users/ — порт list_user_options/create_user_option ──
#
# Р3 (без S2S): исходник проксировал user-service; здесь оба зовут
# apps.users.interface.{list_users_brief,create_user} напрямую. Гейтинг —
# access.can_list_user_options (senior+)/can_manage_user_options (lead) —
# ровно как HR-исходник, НЕ грубый api_view(admin=True).

# patronymic/phone добавлены сверкой идентичности Сотрудник<->Аккаунт
# (docs/superpowers/specs/2026-08-25-hr-identity-sync-design.md §10) — форма
# создания сотрудника сеет ими карточку. bio/avatar_url в списке намеренно
# отсутствуют: они нужны для ОДНОГО выбранного пользователя и приходят
# точечной ручкой employees/users/<id>/prefill/ (см. test_identity_prefill_api).
USER_OPTION_FIELDS = {"id", "full_name", "email", "first_name", "last_name",
                      "patronymic", "phone"}


@pytest.mark.django_db
def test_users_get_requires_jwt():
    resp = Client().get(f"{BASE}/users/")
    assert resp.status_code == 401


@pytest.mark.django_db
def test_users_get_403_without_hr_access(auth):
    resp = Client().get(f"{BASE}/users/", **auth)
    assert resp.status_code == 403
    assert resp.json()["detail"] == "HR access required"


@pytest.mark.django_db
def test_users_get_403_below_senior(middle):
    _emp, headers = middle
    resp = Client().get(f"{BASE}/users/", **headers)
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Senior HR access required"


@pytest.mark.django_db
def test_users_get_200_for_senior(senior):
    _emp, headers = senior
    resp = Client().get(f"{BASE}/users/", **headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.django_db
def test_users_get_200_for_lead(lead):
    _emp, headers = lead
    resp = Client().get(f"{BASE}/users/", **headers)
    assert resp.status_code == 200


@pytest.mark.django_db
def test_users_get_200_for_admin(admin_auth):
    resp = Client().get(f"{BASE}/users/", **admin_auth)
    assert resp.status_code == 200


@pytest.mark.django_db
def test_users_get_shape_and_includes_seeded_users(senior):
    _emp, headers = senior
    resp = Client().get(f"{BASE}/users/", **headers)
    body = resp.json()
    assert len(body) >= 1
    row = body[0]
    assert set(row) == USER_OPTION_FIELDS


@pytest.mark.django_db
def test_users_get_no_slash_variant(senior):
    _emp, headers = senior
    resp = Client().get(f"{BASE}/users", **headers)
    assert resp.status_code == 200


@pytest.mark.django_db
def test_users_post_requires_jwt():
    resp = Client().post(
        f"{BASE}/users/", data='{"email": "x@htq.test"}', content_type="application/json",
    )
    assert resp.status_code == 401


@pytest.mark.django_db
def test_users_post_403_without_hr_access(auth):
    resp = Client().post(
        f"{BASE}/users/", data='{"email": "x@htq.test"}', content_type="application/json", **auth,
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "HR access required"


@pytest.mark.django_db
def test_users_post_403_below_lead(senior):
    """can_list_user_options (senior) is NOT enough to create — needs
    can_manage_user_options (lead)."""
    _emp, headers = senior
    resp = Client().post(
        f"{BASE}/users/", data='{"email": "x@htq.test"}', content_type="application/json", **headers,
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "CO HR access required"


@pytest.mark.django_db
def test_users_post_201_for_lead_creates_user(lead):
    _emp, headers = lead
    resp = Client().post(
        f"{BASE}/users/",
        data='{"first_name": "New", "last_name": "Hire", "patronymic": "P", "email": "new-hire@htq.test", "password": "Str0ng!Passw0rd"}',
        content_type="application/json",
        **headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert set(body) == USER_OPTION_FIELDS
    assert body["email"] == "new-hire@htq.test"
    assert body["first_name"] == "New"
    assert body["last_name"] == "Hire"
    assert body["full_name"] == "New Hire"

    from apps.users.models import User as _User
    created = _User.objects.get(email="new-hire@htq.test")
    assert created.must_change_password is True
    assert created.username == "new-hire"


@pytest.mark.django_db
def test_users_post_201_for_admin(admin_auth):
    resp = Client().post(
        f"{BASE}/users/",
        data='{"first_name": "Admin", "last_name": "Made", "email": "admin-made@htq.test", "password": "Str0ng!Passw0rd"}',
        content_type="application/json",
        **admin_auth,
    )
    assert resp.status_code == 201


@pytest.mark.django_db
def test_users_post_409_on_duplicate_email(lead):
    _emp, headers = lead
    Client().post(
        f"{BASE}/users/",
        data='{"first_name": "First", "last_name": "One", "email": "dupe@htq.test", "password": "Str0ng!Passw0rd"}',
        content_type="application/json",
        **headers,
    )
    resp = Client().post(
        f"{BASE}/users/",
        data='{"first_name": "Second", "last_name": "One", "email": "dupe@htq.test", "password": "Str0ng!Passw0rd"}',
        content_type="application/json",
        **headers,
    )
    assert resp.status_code == 409


@pytest.mark.django_db
def test_users_post_422_invalid_email(lead):
    _emp, headers = lead
    resp = Client().post(
        f"{BASE}/users/",
        data='{"first_name": "Bad", "last_name": "Email", "email": "not-an-email", "password": "Str0ng!Passw0rd"}',
        content_type="application/json",
        **headers,
    )
    assert resp.status_code == 422


@pytest.mark.django_db
def test_users_post_no_slash_variant(lead):
    _emp, headers = lead
    resp = Client().post(
        f"{BASE}/users",
        data='{"first_name": "No", "last_name": "Slash", "email": "no-slash@htq.test", "password": "Str0ng!Passw0rd"}',
        content_type="application/json",
        **headers,
    )
    assert resp.status_code == 201


# ── GET /me/card ──────────────────────────────────────────────────────────────
#
# Порт employees.py::my_employee_card исходника (зовёт EmployeeCardService.
# build_card(employee.id, mode="full", access=...)) — резолвит СВОЙ Employee
# ровно как /me/ и /me/pmos (user_id||email), БЕЗ require_hr_access: полная
# карточка (email/phone/manager/subordinates/pmos) видна всегда, а секция t2
# внутри неё гейтится ПОЛЕВЫМ RBAC (см. test_employee_card_api.py) — без
# единого hr.card.*.view ключа t2 приходит пустым словарём, не 403.

@pytest.mark.django_db
def test_me_card_404_when_no_employee_profile(auth):
    resp = Client().get(f"{BASE}/me/card", **auth)
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Employee profile not found"


@pytest.mark.django_db
def test_me_card_returns_full_shape_including_contacts(junior):
    emp, headers = junior
    resp = Client().get(f"{BASE}/me/card", **headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == emp.id
    assert body["full_name"] == f"{emp.last_name} {emp.first_name}".strip()
    assert body["email"] == emp.email
    assert body["phone"] == emp.phone
    assert body["department"] == {"id": emp.department_id, "name": emp.department.name,
                                   "path": emp.department.path}
    assert body["position"] == {"id": emp.position_id, "title": emp.position.title,
                                 "grade": emp.position.grade, "level": emp.position.level}
    assert body["subordinates"] == []
    assert body["pmos"] == []


@pytest.mark.django_db
def test_me_card_t2_empty_without_any_card_permission(junior):
    """junior не несёт ни одного hr.card.* ключа — t2 приходит пустым, но
    сам эндпойнт НЕ 403: /me/card не завёрнут в require_hr_access."""
    _emp_, headers = junior
    resp = Client().get(f"{BASE}/me/card", **headers)
    assert resp.status_code == 200
    assert resp.json()["t2"] == {}


@pytest.mark.django_db
def test_me_card_t2_empty_for_middle(middle):
    """После удаления секции certs у middle не остаётся ни одного hr.card.*
    view-ключа НА Т-2 (groups — отдельный ресурс, не секция t2): тело пустое,
    как и у junior, но эндпойнт по-прежнему 200."""
    _emp_, headers = middle
    resp = Client().get(f"{BASE}/me/card", **headers)
    assert resp.status_code == 200
    assert resp.json()["t2"] == {}


@pytest.mark.django_db
def test_me_card_manager_is_department_head(hr_dep):
    head_pos = _pos("Head", hr_dep, weight=280)
    head = _emp(hr_dep, head_pos, "card-head@htq.test")
    hr_dep.manager = head
    hr_dep.save()

    sub_pos = _pos("Sub", hr_dep, weight=281)
    user, headers = _user_auth("card-sub@htq.test")
    _sub = _emp(hr_dep, sub_pos, "card-sub@htq.test", user_id=user.id)

    resp = Client().get(f"{BASE}/me/card", **headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["manager"]["id"] == head.id
    assert body["manager"]["email"] == head.email  # mode=full -> contacts included


@pytest.mark.django_db
def test_me_card_subordinates_are_direct_department_reports(hr_dep):
    head_pos = _pos("Head2", hr_dep, weight=282)
    user, headers = _user_auth("card-head2@htq.test")
    head = _emp(hr_dep, head_pos, "card-head2@htq.test", user_id=user.id)
    hr_dep.manager = head
    hr_dep.save()

    report_pos = _pos("Report", hr_dep, weight=283)
    report = _emp(hr_dep, report_pos, "card-report@htq.test")

    resp = Client().get(f"{BASE}/me/card", **headers)
    assert resp.status_code == 200
    subs = resp.json()["subordinates"]
    assert [s["id"] for s in subs] == [report.id]


# ── GET /{id}/card ───────────────────────────────────────────────────────────
#
# Порт employees.py::employee_card исходника — ТА ЖЕ пара require_hr_access +
# _require_visible_employee, что history/documents/pmos выше.

@pytest.mark.django_db
def test_id_card_forbidden_without_any_hr_access(auth, hr_dep):
    target = _emp(hr_dep, _pos("C1", hr_dep, weight=290), "card-target1@htq.test")
    resp = Client().get(f"{BASE}/{target.id}/card", **auth)
    assert resp.status_code == 403
    assert resp.json()["detail"] == "HR access required"


@pytest.mark.django_db
def test_id_card_missing_employee_404(admin_auth):
    resp = Client().get(f"{BASE}/999999/card", **admin_auth)
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Employee not found"


@pytest.mark.django_db
def test_id_card_other_department_returns_404_not_403(middle, other_dep):
    _owner, headers = middle
    target = _emp(other_dep, _pos("C2", other_dep, weight=291), "card-target2@htq.test")
    resp = Client().get(f"{BASE}/{target.id}/card", **headers)
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Employee not found"


@pytest.mark.django_db
def test_id_card_admin_sees_all_t2_sections_and_pmos(admin_auth, hr_dep):
    target = _emp(hr_dep, _pos("C3", hr_dep, weight=292), "card-target3@htq.test")
    pmo = PMO.objects.create(name="PMO Card", code="CARD1")
    PMOMember.objects.create(pmo=pmo, employee=target, from_date=datetime.date(2024, 1, 1))

    resp = Client().get(f"{BASE}/{target.id}/card", **admin_auth)
    assert resp.status_code == 200
    body = resp.json()
    assert set(body["t2"].keys()) == {"financial", "personal"}
    assert [p["pmo_id"] for p in body["pmos"]] == [pmo.id]


@pytest.mark.django_db
def test_id_card_trailing_slash_variant(admin_auth, hr_dep):
    target = _emp(hr_dep, _pos("C4", hr_dep, weight=293), "card-target4@htq.test")
    assert Client().get(f"{BASE}/{target.id}/card/", **admin_auth).status_code == 200


# ── card_t2 в теле создания/обновления (единый атомарный запрос) ────────────

@pytest.fixture
def creator_no_financial(db, hr_dep):
    """Явная матрица прав: МОЖЕТ создавать/править сотрудников и править
    certs, НО НЕ имеет hr.card.financial.edit. Нужна, чтобы доказать, что
    отказ на секции Т-2 откатывает и само создание сотрудника."""
    pos = _pos(
        "Custom Recruiter", hr_dep, weight=250,
        permissions={"permissions": [
            "hr.employees.view", "hr.employees.view.all", "hr.employees.create",
            "hr.employees.edit", "hr.card.certs.view", "hr.card.certs.edit",
        ]},
    )
    user, headers = _user_auth("create-no-fin@htq.test")
    emp = _emp(hr_dep, pos, "create-no-fin@htq.test", user_id=user.id)
    return emp, headers


def _create_body(dep, pos, email, **extra):
    body = {
        "first_name": "Пётр", "last_name": "Петров", "email": email,
        "department_id": dep.id, "position_id": pos.id,
        "hire_date": "2026-08-03", "status": "active",
    }
    body.update(extra)
    return body


@pytest.mark.django_db
def test_create_employee_with_card_t2_writes_card(admin_auth, hr_dep):
    pos = _pos("Инженер", hr_dep, weight=310)
    resp = Client().post(
        f"{BASE}/",
        data=_create_body(hr_dep, pos, "with-t2@htq.test", card_t2={
            "financial": {"salary": "450000", "bonus": "50000", "bank_account": "KZ42"},
            "personal": {"citizenship": "KZ", "birth_date": "1990-05-05"},
            "certs": {"sro_permit_number": "СРО-11"},
        }),
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 201, resp.content
    employee_id = resp.json()["id"]

    card = EmployeeCard.objects.get(employee_id=employee_id)
    assert str(card.salary) == "450000.00"
    assert card.citizenship == "KZ"
    assert card.birth_date == datetime.date(1990, 5, 5)
    assert card.sro_permit_number == "СРО-11"


@pytest.mark.django_db
def test_create_employee_without_card_t2_unchanged(admin_auth, hr_dep):
    """Тела без card_t2 обрабатываются ровно как раньше — карточка не заводится."""
    pos = _pos("Инженер-2", hr_dep, weight=311)
    resp = Client().post(
        f"{BASE}/", data=_create_body(hr_dep, pos, "no-t2@htq.test"),
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 201, resp.content
    assert not EmployeeCard.objects.filter(employee_id=resp.json()["id"]).exists()


@pytest.mark.django_db
def test_create_employee_rolls_back_when_card_section_forbidden(creator_no_financial, hr_dep):
    """Главный инвариант атомарности: 403 на секции Т-2 означает, что
    сотрудник НЕ создан — а не «создан наполовину»."""
    _actor, headers = creator_no_financial
    pos = _pos("Инженер-3", hr_dep, weight=312)
    before = Employee.objects.count()

    resp = Client().post(
        f"{BASE}/",
        data=_create_body(hr_dep, pos, "rollback@htq.test", card_t2={
            "financial": {"salary": "1000"},
        }),
        content_type="application/json", **headers,
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Missing permission: hr.card.financial.edit"
    assert Employee.objects.count() == before
    assert not Employee.objects.filter(email="rollback@htq.test").exists()


@pytest.mark.django_db
def test_create_employee_rolls_back_on_invalid_decimal(admin_auth, hr_dep):
    pos = _pos("Инженер-4", hr_dep, weight=313)
    before = Employee.objects.count()

    resp = Client().post(
        f"{BASE}/",
        data=_create_body(hr_dep, pos, "bad-money@htq.test", card_t2={
            "financial": {"salary": "много"},
        }),
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 422
    assert "Invalid decimal for salary" in resp.json()["detail"]
    assert Employee.objects.count() == before


@pytest.mark.django_db
def test_update_employee_with_card_t2_applies_both(admin_auth, hr_dep):
    pos = _pos("Инженер-5", hr_dep, weight=314)
    target = _emp(hr_dep, pos, "upd-t2@htq.test", phone="+7700")

    resp = Client().put(
        f"{BASE}/{target.id}/",
        data={"phone": "+77012345678", "card_t2": {"certs": {"sro_permit_number": "СРО-88"}}},
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 200, resp.content

    target.refresh_from_db()
    assert target.phone == "+77012345678"
    assert EmployeeCard.objects.get(employee_id=target.id).sro_permit_number == "СРО-88"


@pytest.mark.django_db
def test_update_employee_rolls_back_basic_fields_when_card_forbidden(creator_no_financial, hr_dep):
    """Отказ на секции Т-2 откатывает и уже применённые базовые поля."""
    _actor, headers = creator_no_financial
    pos = _pos("Инженер-6", hr_dep, weight=315)
    target = _emp(hr_dep, pos, "upd-rollback@htq.test", phone="+7700")

    resp = Client().put(
        f"{BASE}/{target.id}/",
        data={"phone": "+77019999999", "card_t2": {"financial": {"salary": "1"}}},
        content_type="application/json", **headers,
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Missing permission: hr.card.financial.edit"

    target.refresh_from_db()
    assert target.phone == "+7700"
    assert not EmployeeCard.objects.filter(employee_id=target.id).exists()


# ── Пароль при создании пользователя из HR-формы ────────────────────────────
#
# До этого форма пароль не спрашивала, а apps.users.interface.create_user
# минтил случайный `secrets.token_urlsafe(12)`, которого не видел никто:
# аккаунт заводился, но войти в него было нельзя до админского сброса.
# Пароль стал обязательным, поэтому его отсутствие — 422, а переданный
# должен реально работать при входе.

@pytest.mark.django_db
def test_users_post_422_without_password(lead):
    _emp, headers = lead
    resp = Client().post(
        f"{BASE}/users/",
        data='{"first_name": "No", "last_name": "Password", "email": "no-pwd@htq.test"}',
        content_type="application/json",
        **headers,
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == "Пароль обязателен"

    from apps.users.models import User as _User
    assert not _User.objects.filter(email="no-pwd@htq.test").exists()


@pytest.mark.django_db
def test_users_post_422_on_blank_password(lead):
    """Пробелы — не пароль: иначе форму можно было бы «обойти» пробелом."""
    _emp, headers = lead
    resp = Client().post(
        f"{BASE}/users/",
        data='{"first_name": "Blank", "last_name": "Password", "email": "blank-pwd@htq.test", "password": "   "}',
        content_type="application/json",
        **headers,
    )
    assert resp.status_code == 422


@pytest.mark.django_db
def test_users_post_sets_the_given_password(lead):
    """Главное: переданным паролем действительно можно войти."""
    _emp, headers = lead
    resp = Client().post(
        f"{BASE}/users/",
        data='{"first_name": "Real", "last_name": "Login", "email": "real-login@htq.test", "password": "Str0ng!Passw0rd"}',
        content_type="application/json",
        **headers,
    )
    assert resp.status_code == 201

    from apps.users.models import User as _User
    created = _User.objects.get(email="real-login@htq.test")
    assert created.check_password("Str0ng!Passw0rd")
    # По умолчанию — смена при первом входе (пароль назначал не сам сотрудник).
    assert created.must_change_password is True


@pytest.mark.django_db
def test_users_post_forces_password_change_even_if_client_says_otherwise(lead):
    """Смена пароля при первом входе на этом маршруте НЕ отключаема.

    Пароль назначает HR и видит его открытым текстом, поэтому сотрудник обязан
    сменить его при первом входе. Поля в схеме нет, вьюха проставляет True
    жёстко — присланный клиентом ``false`` должен игнорироваться, а не
    приниматься. Тест бьёт именно в обход UI: через форму такой запрос не
    отправить, а напрямую — сколько угодно.
    """
    _emp, headers = lead
    resp = Client().post(
        f"{BASE}/users/",
        data=('{"first_name": "Keep", "last_name": "Password", "email": "keep-pwd@htq.test",'
              ' "password": "Str0ng!Passw0rd", "must_change_password": false}'),
        content_type="application/json",
        **headers,
    )
    assert resp.status_code == 201

    from apps.users.models import User as _User
    assert _User.objects.get(email="keep-pwd@htq.test").must_change_password is True
