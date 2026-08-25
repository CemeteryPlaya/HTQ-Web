"""Автозаполнение карточки данными аккаунта — исходный запрос владельца.

bio/avatar_url намеренно НЕ входят в список пользователей: они не нужны для
выбора из списка и раздули бы ответ на всех пользователей сразу. Их отдаёт
точечный prefill (спека §10).

План: docs/superpowers/plans/2026-08-25-hr-identity-sync.md, задача 3.
"""
from __future__ import annotations

import datetime

import pytest
from django.test import Client

from apps.hr.models import Department, Employee, Position
from apps.hr.tests.conftest import auth_headers, make_user

BASE = "/api/hr/v1/employees/users"


@pytest.fixture
def senior_auth(db):
    """Senior HR — уровень, у которого есть hr.users.list."""
    dep = Department.objects.create(name="HR", path="hr")
    pos = Position.objects.create(title="Senior HR Manager", department=dep, weight=30)
    user = make_user("hr-senior-prefill@htq.test")
    Employee.objects.create(
        email="hr-senior-prefill@htq.test", department=dep, position=pos,
        hire_date=datetime.date(2024, 1, 9), user_id=user.id,
        first_name="С", last_name="К",
    )
    return auth_headers(user)


@pytest.fixture
def target(db):
    user = make_user(
        "petrov@htq.test", first_name="Пётр", last_name="Петров",
        patronymic="Сергеевич", phone="+7 705 111-22-33", bio="Инженер",
    )
    user.avatar_url = "/api/media/v1/files/abc"
    user.save()
    return user


@pytest.mark.django_db
def test_prefill_requires_jwt(target):
    assert Client().get(f"{BASE}/{target.id}/prefill/").status_code == 401


@pytest.mark.django_db
def test_prefill_returns_account_fields(senior_auth, target):
    res = Client().get(f"{BASE}/{target.id}/prefill/", **senior_auth)

    assert res.status_code == 200
    body = res.json()
    assert body["patronymic"] == "Сергеевич"
    assert body["phone"] == "+7 705 111-22-33"
    assert body["bio"] == "Инженер"
    assert body["avatar_url"] == "/api/media/v1/files/abc"


@pytest.mark.django_db
def test_prefill_unknown_user_404(senior_auth):
    assert Client().get(f"{BASE}/999999/prefill/", **senior_auth).status_code == 404


@pytest.mark.django_db
def test_prefill_without_hr_access_is_403(db, target):
    outsider = make_user("nobody@htq.test")
    res = Client().get(f"{BASE}/{target.id}/prefill/", **auth_headers(outsider))
    assert res.status_code == 403


@pytest.mark.django_db
def test_user_options_carry_patronymic_and_phone(senior_auth, target):
    res = Client().get(f"{BASE}/", **senior_auth)

    assert res.status_code == 200
    row = next(r for r in res.json() if r["id"] == target.id)
    assert row["patronymic"] == "Сергеевич"
    assert row["phone"] == "+7 705 111-22-33"
    # вес списка: тяжёлые поля остаются за точечной ручкой
    assert "bio" not in row
