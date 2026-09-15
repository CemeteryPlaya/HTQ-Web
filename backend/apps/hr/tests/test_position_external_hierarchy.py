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


@pytest.fixture
def department(db):
    return Department.objects.create(name="Руководство", path="upr")


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
