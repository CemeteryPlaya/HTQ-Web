"""Два поля должности, которыми включается внешняя иерархия (roadmap §5.B).

Внешняя иерархия выводится из дерева владения компаниями и распространяется
только на руководящие должности — оговорка «относится к руководителям» часть
правила заказчика, а не уточнение: без неё рядовой сотрудник холдинга
оказался бы начальником директора дочерней компании.
"""

import datetime

import pytest
from django.core.exceptions import ValidationError

from apps.hr.models import Department, ExternalHierarchy, Position
from apps.hr.tests.conftest import auth_headers
from apps.users.models import User, UserStatus


@pytest.fixture
def department(db):
    return Department.objects.create(name="Руководство", path="upr")


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
def test_position_is_not_a_manager_by_default(department):
    """Бэкфилла нет: молча раздать видимость чужих компаний нельзя."""
    pos = Position.objects.create(title="Инженер", department=department, weight=100)
    pos.refresh_from_db()
    assert pos.is_manager is False


@pytest.mark.django_db
def test_external_hierarchy_defaults_to_inherit(department):
    """Участие включается одним флажком «руководящая», а не двумя действиями."""
    pos = Position.objects.create(title="Инженер", department=department, weight=100)
    pos.refresh_from_db()
    assert pos.external_hierarchy == ExternalHierarchy.INHERIT


@pytest.mark.django_db
def test_managerial_position_can_opt_out_of_the_external_hierarchy(department):
    pos = Position.objects.create(
        title="Главный бухгалтер", department=department, weight=110,
        is_manager=True, external_hierarchy=ExternalHierarchy.NONE,
    )
    pos.full_clean()
    pos.refresh_from_db()
    assert (pos.is_manager, pos.external_hierarchy) == (True, "none")


@pytest.mark.django_db
def test_unknown_external_hierarchy_value_is_rejected(department):
    pos = Position(title="Директор", department=department, weight=10,
                   external_hierarchy="maybe")
    with pytest.raises(ValidationError):
        pos.full_clean()


@pytest.mark.django_db
def test_ordinary_position_with_default_inherit_is_valid(department):
    """Пара «не руководитель + inherit» ЗАКОННА и ограничением БД не запрещена.

    inherit — значение по умолчанию, поэтому запрет сделал бы нелегальной
    каждую обычную должность. Оба условия проверяет разрешение прав
    (apps/access/services/hierarchy.py), а не схема.
    """
    pos = Position(title="Слесарь", department=department, weight=900)
    pos.full_clean()  # не должно поднять ValidationError


# ── Шов наружу ────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_employee_brief_carries_both_fields(department):
    """Единственный шов внешней иерархии с кадровым доменом.

    apps.access читает их отсюда и больше ниоткуда: модели HR он не
    импортирует ни одной строкой.
    """
    from apps.hr import interface as hr
    from apps.hr.models import Employee

    pos = Position.objects.create(title="Генеральный директор", department=department,
                                  weight=10, is_manager=True)
    Employee.objects.create(
        first_name="Ерлан", last_name="Абдрахманов", email="ceo@htq.test",
        department=department, position=pos,
        hire_date=datetime.date(2024, 1, 9), user_id=4242,
    )

    brief = hr.get_employee_brief(4242)
    assert brief["is_manager"] is True
    assert brief["external_hierarchy"] == "inherit"
    # Аддитивность: ключи, которые читает действующий фронт, на месте.
    assert {"id", "full_name", "department_id", "position_id",
            "position_title", "status"} <= set(brief)


@pytest.mark.django_db
def test_serialize_exposes_both_fields(department):
    from apps.hr.services import position_service

    pos = Position.objects.create(title="Технический директор", department=department,
                                  weight=20, is_manager=True,
                                  external_hierarchy=ExternalHierarchy.NONE)
    row = position_service.serialize(pos)
    assert row["is_manager"] is True
    assert row["external_hierarchy"] == "none"


@pytest.mark.django_db
def test_patch_sets_the_fields(client, department, admin_headers):
    pos = Position.objects.create(title="Операционный директор", department=department,
                                  weight=30)
    res = client.patch(
        f"/api/hr/v1/positions/{pos.id}/",
        data='{"is_manager": true, "external_hierarchy": "none"}',
        content_type="application/json", **admin_headers,
    )
    assert res.status_code == 200
    assert res.json()["is_manager"] is True
    assert res.json()["external_hierarchy"] == "none"
    pos.refresh_from_db()
    assert (pos.is_manager, pos.external_hierarchy) == (True, "none")


@pytest.mark.django_db
def test_patch_rejects_an_unknown_external_hierarchy_value(client, department, admin_headers):
    pos = Position.objects.create(title="Директор по строительству",
                                  department=department, weight=40)
    res = client.patch(
        f"/api/hr/v1/positions/{pos.id}/",
        data='{"external_hierarchy": "sometimes"}',
        content_type="application/json", **admin_headers,
    )
    assert res.status_code == 422
