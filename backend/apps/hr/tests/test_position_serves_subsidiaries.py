"""Признак «должность обслуживает дочерние компании» (roadmap §5.C).

Отдельный от ``is_manager`` намеренно, и это решение заказчика, а не вкус:
в холдинге 4 руководителя и 8 менеджеров, а обслуживают дочерние компании
именно менеджеры — главбух, кадровый бухгалтер, экономист, ГИП, менеджер ПТО,
менеджер по кадрам, менеджер по закупкам, системный администратор. Пометить их
руководящими значило бы объявить главбуха холдинга начальником сотрудников ДО
и вывести его во внешнюю иерархию блока B, где ему делать нечего.
"""

import datetime

import pytest

from apps.hr.models import Department, Position
from apps.hr.tests.conftest import auth_headers
from apps.users.models import User, UserStatus


@pytest.fixture
def department(db):
    return Department.objects.create(name="Финансы", path="fin")


@pytest.fixture
def admin_headers(db):
    """is_staff=True — писать позиции может только elevated (require_hr_write)."""
    user = User.objects.create(
        username="hr-admin", email="hr-admin@htq.test", password="x",
        status=UserStatus.ACTIVE, is_staff=True,
    )
    user.set_password("Adm1n!Pass")
    user.save()
    return auth_headers(user)


@pytest.mark.django_db
def test_position_does_not_serve_subsidiaries_by_default(department):
    """Бэкфилла нет: права в чужих компаниях не раздаются догадкой."""
    pos = Position.objects.create(title="Инженер", department=department, weight=100)
    pos.refresh_from_db()
    assert pos.serves_subsidiaries is False


@pytest.mark.django_db
def test_serving_position_need_not_be_managerial(department):
    """Главбух холдинга обслуживает ДО, но начальником их сотрудников не является."""
    pos = Position.objects.create(
        title="Главный бухгалтер", department=department, weight=110,
        serves_subsidiaries=True,
    )
    pos.full_clean()
    pos.refresh_from_db()
    assert (pos.serves_subsidiaries, pos.is_manager) == (True, False)


@pytest.mark.django_db
def test_the_two_flags_are_independent(department):
    """Руководящая и обслуживающая — разные вопросы, любое сочетание законно."""
    pos = Position.objects.create(
        title="Финансовый директор", department=department, weight=20,
        is_manager=True, serves_subsidiaries=True,
    )
    pos.full_clean()
    pos.refresh_from_db()
    assert (pos.is_manager, pos.serves_subsidiaries) == (True, True)


# ── Шов наружу ────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_employee_brief_carries_the_field(department):
    """Единственный шов признака с кадровым доменом.

    apps.access читает его отсюда и больше ниоткуда: модели HR он не
    импортирует ни одной строкой.
    """
    from apps.hr import interface as hr
    from apps.hr.models import Employee

    pos = Position.objects.create(title="Главный бухгалтер", department=department,
                                  weight=10, serves_subsidiaries=True)
    Employee.objects.create(
        first_name="Айгуль", last_name="Сериккызы", email="cfo@htq.test",
        department=department, position=pos,
        hire_date=datetime.date(2024, 1, 9), user_id=4243,
    )

    brief = hr.get_employee_brief(4243)
    assert brief["serves_subsidiaries"] is True
    # Аддитивность: ключи, которые читает действующий фронт, на месте.
    assert {"id", "full_name", "department_id", "position_id",
            "position_title", "status", "is_manager",
            "external_hierarchy"} <= set(brief)


@pytest.mark.django_db
def test_serialize_exposes_the_field(department):
    from apps.hr.services import position_service

    pos = Position.objects.create(title="Экономист", department=department,
                                  weight=20, serves_subsidiaries=True)
    row = position_service.serialize(pos)
    assert row["serves_subsidiaries"] is True


@pytest.mark.django_db
def test_patch_sets_the_field(client, department, admin_headers):
    pos = Position.objects.create(title="Менеджер ПТО", department=department,
                                  weight=30)
    res = client.patch(
        f"/api/hr/v1/positions/{pos.id}/",
        data='{"serves_subsidiaries": true}',
        content_type="application/json", **admin_headers,
    )
    assert res.status_code == 200
    assert res.json()["serves_subsidiaries"] is True
    pos.refresh_from_db()
    assert pos.serves_subsidiaries is True
