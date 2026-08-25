"""Общие фикстуры для тестов сверки идентичности Сотрудник ↔ Аккаунт.

Живут в conftest, а не в одном из тестовых модулей: связку «отдел + должность
+ сотрудник + его аккаунт» строят пять файлов (identity_models,
identity_sync_service, identity_request_service, identity_decide,
identity_nightly, identity_requests_api), и копия в каждом расходилась бы при
первой же правке модели.

Имена намеренно не пересекаются с фикстурами существующих модулей
(``auth``/``senior``/``lead`` в test_employees_api.py): те собирают HR-уровни
через должности и остаются там, где были.

Спека: docs/superpowers/specs/2026-08-25-hr-identity-sync-design.md
"""
from __future__ import annotations

import datetime

import pytest

from apps.hr.models import Department, Employee, Position
from apps.users.models import User, UserStatus
from htqweb.authn.jwt import issue_token_pair


def make_user(email: str, **kwargs) -> User:
    user = User.objects.create(
        username=email.split("@")[0], email=email, password="x",
        status=UserStatus.ACTIVE, **kwargs,
    )
    user.set_password("S3cret!Pass1")
    user.save()
    return user


def auth_headers(user: User) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {issue_token_pair(user)['access']}"}


@pytest.fixture
def department(db):
    return Department.objects.create(name="Строительство", path="build")


@pytest.fixture
def position(db, department):
    return Position.objects.create(title="Инженер", department=department, weight=10)


@pytest.fixture
def other_position(db, department):
    return Position.objects.create(title="Ведущий инженер", department=department, weight=20)


@pytest.fixture
def account(db):
    """Аккаунт сотрудника — владелец идентичности."""
    return make_user(
        "ivanov@htq.test", first_name="Иван", last_name="Иванов",
        patronymic="Петрович", phone="+7 705 111-22-33", bio="Инженер ПТО",
    )


@pytest.fixture
def employee(db, department, position, account):
    """Сотрудник со связанным аккаунтом и КОПИЕЙ его идентичности.

    Копия сразу согласована с аккаунтом: тест, которому нужно расхождение,
    вносит его сам и тем самым явно показывает, что именно проверяет.
    """
    return Employee.objects.create(
        email="ivanov@htq.test", department=department, position=position,
        hire_date=datetime.date(2024, 1, 9), user_id=account.id,
        first_name=account.first_name, last_name=account.last_name,
        middle_name=account.patronymic, phone=account.phone, bio=account.bio,
    )


@pytest.fixture
def manager_employee(db, department, position):
    """Руководитель отдела — второй по лестнице подтверждающий (спека §6.2)."""
    user = make_user("boss@htq.test", first_name="Пётр", last_name="Начальников")
    return Employee.objects.create(
        email="boss@htq.test", department=department, position=position,
        hire_date=datetime.date(2020, 1, 9), user_id=user.id,
        first_name="Пётр", last_name="Начальников",
    )
