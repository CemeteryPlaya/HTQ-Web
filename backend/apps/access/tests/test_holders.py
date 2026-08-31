"""Кто держит роль — данные для диалога удаления.

Отказ удалить занятую роль обязан называть имена. Одно число («назначена трём
должностям») не говорит, к кому идти: снять роль по такому ответу нельзя,
придётся искать вручную по всем компаниям — а компаний может быть несколько, и
кадровые данные каждой лежат в своей схеме.
"""

import datetime
import logging

import pytest

from apps.access.models import PositionRole, Role, RoleAssignment, ScopeKind
from apps.access.services import holders as holders_svc


@pytest.fixture
def role(db):
    return Role.objects.create(code="under-test", title="Проверяемая")


@pytest.fixture
def employee_in_company(company_schema, django_user_model):
    """Сотрудник с должностью и учёткой ВНУТРИ схемы компании."""
    from htqweb.tenancy.db import use_company

    slug = company_schema["slug"]
    # status="active", а не только Django-флаг is_active: пригодность учётки
    # apps.users определяет СВОИМ полем (interface._brief_from_values), и
    # resolve_position_users смотрит именно на него.
    account = django_user_model.objects.create_user(
        username="petrov", email="petrov@htq.test", password="x",
        first_name="Пётр", last_name="Петров", status="active")

    with use_company(slug):
        from apps.hr.models import Department, Employee, Position

        department = Department.objects.create(name="Строительство", path="build")
        position = Position.objects.create(title="Прораб", department=department,
                                           weight=120)
        Employee.objects.create(
            first_name="Пётр", last_name="Петров", email="petrov@htq.test",
            department=department, position=position,
            hire_date=datetime.date(2024, 3, 1), user_id=account.id,
        )
        ids = {"slug": slug, "position_id": position.id, "user_id": account.id}

    yield ids

    from django.db import connection
    connection.check_constraints()


@pytest.mark.django_db
def test_unused_role_has_no_holders(role):
    assert holders_svc.holders(role.id) == []


@pytest.mark.django_db
def test_position_holder_carries_name_company_department_and_position(
        role, employee_in_company):
    PositionRole.objects.create(company_slug=employee_in_company["slug"],
                                position_id=employee_in_company["position_id"],
                                role=role)

    rows = holders_svc.holders(role.id)

    assert len(rows) == 1
    assert rows[0] == {
        "user_id": employee_in_company["user_id"],
        "company": employee_in_company["slug"],
        "source": holders_svc.POSITION,
        "full_name": "Петров Пётр",
        "department": "Строительство",
        "position": "Прораб",
        "position_id": employee_in_company["position_id"],
    }


@pytest.mark.django_db
def test_personal_holder_is_marked_as_such(role, employee_in_company):
    """Должностного снимают у должности, личного — у человека: путь разный."""
    RoleAssignment.objects.create(company_slug=employee_in_company["slug"],
                                  user_id=employee_in_company["user_id"], role=role,
                                  scope_kind=ScopeKind.COMPANY, scope_id=None)

    rows = holders_svc.holders(role.id)

    assert [row["source"] for row in rows] == [holders_svc.PERSONAL]
    assert rows[0]["position_id"] is None


@pytest.mark.django_db
def test_holder_without_an_employee_card_still_has_a_name(
        role, company_schema, django_user_model):
    """Директор холдинга или подрядчик: карточки нет, а имя нужно."""
    account = django_user_model.objects.create_user(
        username="boss", email="boss@htq.test", password="x",
        first_name="Иван", last_name="Директоров")
    RoleAssignment.objects.create(company_slug=company_schema["slug"],
                                  user_id=account.id, role=role,
                                  scope_kind=ScopeKind.COMPANY, scope_id=None)

    rows = holders_svc.holders(role.id)

    assert len(rows) == 1
    assert rows[0]["full_name"]
    assert rows[0]["department"] is None
    assert rows[0]["position"] is None


@pytest.mark.django_db
def test_unreachable_company_is_reported_not_silently_skipped(role, caplog, monkeypatch):
    """Иначе администратор решит, что роль свободна, и удалит её.

    Отказ подстраивается искусственно: в тестовой БД тенантные таблицы лежат в
    ``public``, поэтому несуществующая схема НЕ роняет запрос — ``SET
    search_path`` на отсутствующую схему Postgres принимает молча, а данные
    находятся в ``public``. В проде после ``tenancy_bootstrap`` это уже не так,
    и обработчик нужен именно там.
    """
    from htqweb.tenancy import db as tenancy_db

    def boom(_slug):
        raise RuntimeError("схема недоступна")

    monkeypatch.setattr(tenancy_db, "use_company", boom)
    PositionRole.objects.create(company_slug="нет-такой-компании",
                                position_id=1, role=role)

    with caplog.at_level(logging.INFO, logger="htqweb.fallback"):
        rows = holders_svc.holders(role.id)

    assert rows == []
    assert "access.holders.company_unavailable" in caplog.text
