"""Признак «должность обслуживает дочерние компании» (roadmap §5.C).

Отдельный от ``is_manager`` намеренно, и это решение заказчика, а не вкус:
в холдинге 4 руководителя и 8 менеджеров, а обслуживают дочерние компании
именно менеджеры — главбух, кадровый бухгалтер, экономист, ГИП, менеджер ПТО,
менеджер по кадрам, менеджер по закупкам, системный администратор. Пометить их
руководящими значило бы объявить главбуха холдинга начальником сотрудников ДО
и вывести его во внешнюю иерархию блока B, где ему делать нечего.
"""

import pytest

from apps.hr.models import Department, Position


@pytest.fixture
def department(db):
    return Department.objects.create(name="Финансы", path="fin")


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
