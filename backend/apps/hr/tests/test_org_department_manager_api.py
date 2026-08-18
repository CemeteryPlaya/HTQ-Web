"""Контракт PUT /api/hr/v1/org/departments/{id}/manager — не порт, закрывает
дыру: ``PATCH /departments/{id}/`` не может сбросить ``manager_id`` в null,
потому что ``DepartmentUpdate`` применяется через ``model_dump(exclude_none=True)``
(зафиксировано ``test_departments_api.py::test_update_ignores_none_fields`` —
тот тест НЕ трогается этой задачей, он пинит, что старый путь остаётся как
был). Отдельная ручка вместо починки ``update_department``: та PATCH-семантика
задокументирована как намеренный порт, и её смена задела бы name/path/
description/is_active по всему приложению.

Авторизация — ``hr.org.edit`` (HR senior/lead), как и у ``/org/relations``
после смены гейта (см. test_org_api.py).

Зафиксированные ловушки:
  * ``{"employee_id": null}`` И отсутствие поля вовсе — ОБА снимают
    руководителя (Pydantic default ``None``, а не exclude_none);
  * 404 — неизвестный отдел ИЛИ неизвестный/мягко удалённый сотрудник;
  * 422 — сотрудник существует, но не ``status="active"``;
  * ответ несёт то же подмножество полей, что ``meta`` dept-узла в
    ``get_org_tree``, чтобы панель обновилась без повторного запроса дерева.

План: docs/plans/2026-07-20-hr-domain.md
"""
from __future__ import annotations

import datetime

import pytest
from django.test import Client

from apps.hr.models import Department, Employee, Position
from apps.users.models import User, UserStatus
from htqweb.authn.jwt import issue_token_pair

BASE = "/api/hr/v1/org/departments"


@pytest.fixture
def dep(db):
    return Department.objects.create(name="ИТ", path="it")


@pytest.fixture
def hr_dep(db):
    return Department.objects.create(name="HR", path="hr-dept")


def _pos(title, dep, weight, **kw):
    return Position.objects.create(title=title, department=dep, weight=weight, **kw)


def _emp(dep, pos, email, **kw):
    return Employee.objects.create(
        first_name="И", last_name="И", email=email, department=dep, position=pos,
        hire_date=datetime.date(2024, 1, 9), **kw,
    )


@pytest.fixture
def auth(db):
    user = User.objects.create(
        username="orgmgr-user", email="orgmgr-user@htq.test", password="x", status=UserStatus.ACTIVE,
    )
    user.set_password("S3cret!")
    user.save()
    return {"HTTP_AUTHORIZATION": f"Bearer {issue_token_pair(user)['access']}"}


@pytest.fixture
def admin_auth(db):
    user = User.objects.create(
        username="orgmgr-admin", email="orgmgr-admin@htq.test", password="x", status=UserStatus.ACTIVE,
        is_staff=True,
    )
    user.set_password("Adm1n!Pass")
    user.save()
    return {"HTTP_AUTHORIZATION": f"Bearer {issue_token_pair(user)['access']}"}


@pytest.fixture
def senior_auth(db, hr_dep):
    pos = _pos("Senior HR Manager", hr_dep, weight=941)
    user = User.objects.create(
        username="orgmgr-senior", email="orgmgr-senior@htq.test", password="x", status=UserStatus.ACTIVE,
    )
    user.set_password("S3cret!Pass1")
    user.save()
    Employee.objects.create(
        first_name="И", last_name="И", email="orgmgr-senior@htq.test",
        department=hr_dep, position=pos, hire_date=datetime.date(2024, 1, 9), user_id=user.id,
    )
    return {"HTTP_AUTHORIZATION": f"Bearer {issue_token_pair(user)['access']}"}


# ── auth ──────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_requires_jwt(dep):
    resp = Client().put(
        f"{BASE}/{dep.id}/manager", data={}, content_type="application/json",
    )
    assert resp.status_code == 401


@pytest.mark.django_db
def test_forbidden_without_hr_access(auth, dep):
    resp = Client().put(
        f"{BASE}/{dep.id}/manager", data={"employee_id": None},
        content_type="application/json", **auth,
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Missing permission: hr.org.edit"


# ── PUT /org/departments/{id}/manager ────────────────────────────────────────

@pytest.mark.django_db
def test_set_manager_by_employee_id(senior_auth, dep):
    pos = _pos("Директор", dep, weight=10)
    manager = _emp(dep, pos, "director@htq.test")

    resp = Client().put(
        f"{BASE}/{dep.id}/manager", data={"employee_id": manager.id},
        content_type="application/json", **senior_auth,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["manager_id"] == manager.id
    assert body["manager_position_id"] == pos.id
    dep.refresh_from_db()
    assert dep.manager_id == manager.id


@pytest.mark.django_db
def test_clear_manager_with_explicit_null(senior_auth, dep):
    """Заглавный тест закрываемой дыры: {"employee_id": null} СНИМАЕТ
    руководителя, в отличие от PATCH /departments/{id}/."""
    pos = _pos("Директор", dep, weight=10)
    manager = _emp(dep, pos, "director@htq.test")
    dep.manager = manager
    dep.save(update_fields=["manager"])

    resp = Client().put(
        f"{BASE}/{dep.id}/manager", data={"employee_id": None},
        content_type="application/json", **senior_auth,
    )
    assert resp.status_code == 200
    assert resp.json()["manager_id"] is None
    dep.refresh_from_db()
    assert dep.manager_id is None


@pytest.mark.django_db
def test_clear_manager_with_absent_field(senior_auth, dep):
    """Отсутствие поля в теле — тоже очистка: employee_id: int | None = None
    (Pydantic default), а не exclude_none PATCH-семантика DepartmentUpdate."""
    pos = _pos("Директор", dep, weight=10)
    manager = _emp(dep, pos, "director@htq.test")
    dep.manager = manager
    dep.save(update_fields=["manager"])

    resp = Client().put(
        f"{BASE}/{dep.id}/manager", data={}, content_type="application/json", **senior_auth,
    )
    assert resp.status_code == 200
    assert resp.json()["manager_id"] is None
    dep.refresh_from_db()
    assert dep.manager_id is None


@pytest.mark.django_db
def test_set_manager_allowed_for_admin(admin_auth, dep):
    pos = _pos("Директор", dep, weight=10)
    manager = _emp(dep, pos, "director@htq.test")
    resp = Client().put(
        f"{BASE}/{dep.id}/manager", data={"employee_id": manager.id},
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 200


@pytest.mark.django_db
def test_unknown_department_404(senior_auth):
    resp = Client().put(
        f"{BASE}/999999/manager", data={"employee_id": None},
        content_type="application/json", **senior_auth,
    )
    assert resp.status_code == 404


@pytest.mark.django_db
def test_unknown_employee_404(senior_auth, dep):
    resp = Client().put(
        f"{BASE}/{dep.id}/manager", data={"employee_id": 999999},
        content_type="application/json", **senior_auth,
    )
    assert resp.status_code == 404


@pytest.mark.django_db
def test_soft_deleted_employee_404(senior_auth, dep):
    pos = _pos("Директор", dep, weight=10)
    manager = _emp(dep, pos, "director@htq.test", is_deleted=True)
    resp = Client().put(
        f"{BASE}/{dep.id}/manager", data={"employee_id": manager.id},
        content_type="application/json", **senior_auth,
    )
    assert resp.status_code == 404


@pytest.mark.django_db
def test_inactive_employee_422(senior_auth, dep):
    pos = _pos("Директор", dep, weight=10)
    manager = _emp(dep, pos, "director@htq.test", status="suspended")
    resp = Client().put(
        f"{BASE}/{dep.id}/manager", data={"employee_id": manager.id},
        content_type="application/json", **senior_auth,
    )
    assert resp.status_code == 422


@pytest.mark.django_db
def test_regression_department_patch_still_ignores_null_manager_id(senior_auth, dep):
    """Пин: обычный PATCH /departments/{id}/ НЕ переводили на новую
    семантику — эта задача сознательно не трогала update_department (см.
    test_departments_api.py::test_update_ignores_none_fields)."""
    pos = _pos("Директор", dep, weight=10)
    manager = _emp(dep, pos, "director@htq.test")
    dep.manager = manager
    dep.save(update_fields=["manager"])

    resp = Client().patch(
        f"/api/hr/v1/departments/{dep.id}/", data={"manager_id": None},
        content_type="application/json", **senior_auth,
    )
    assert resp.status_code == 200
    dep.refresh_from_db()
    assert dep.manager_id == manager.id
