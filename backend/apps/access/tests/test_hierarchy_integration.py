# backend/apps/access/tests/test_hierarchy_integration.py
"""Внешняя иерархия на НАСТОЯЩИХ полях должности, без подмены брифа.

test_hierarchy.py проверяет логику обхода дерева, подменяя ответ кадрового
интерфейса, — он писался до того, как поля существовали. Здесь тот же
сценарий проходит целиком: строка Position -> apps.hr.interface ->
apps.access. Оба файла нужны: первый ловит логику обхода, второй — то, что
шов реально сходится.
"""

import pytest

from apps.access.services import hierarchy


@pytest.fixture
def company_tree(db):
    from apps.companies.models import Company, CompanyKind

    holding = Company.objects.create(slug="htq-holding", name="Холдинг",
                                     kind=CompanyKind.HOLDING)
    Company.objects.create(slug="htq-kz", name="КЗ",
                           kind=CompanyKind.CONSTRUCTION, parent=holding)
    return holding


@pytest.mark.django_db
def test_managerial_position_opens_the_subtree(user, employee_with_position, company_tree):
    """Флажок «руководящая» на должности — и подчинённые компании появились."""
    employee_with_position.is_manager = True
    employee_with_position.save(update_fields=["is_manager"])

    assert hierarchy.subordinate_companies(user, "htq-holding") == ["htq-kz"]


@pytest.mark.django_db
def test_opting_out_closes_it_again(user, employee_with_position, company_tree):
    from apps.hr.models import ExternalHierarchy

    employee_with_position.is_manager = True
    employee_with_position.external_hierarchy = ExternalHierarchy.NONE
    employee_with_position.save(update_fields=["is_manager", "external_hierarchy"])

    assert hierarchy.subordinate_companies(user, "htq-holding") == []


@pytest.mark.django_db
def test_ordinary_position_stays_empty(user, employee_with_position, company_tree):
    """Состояние сразу после выкатки: бэкфилла нет, у всех пусто."""
    assert hierarchy.subordinate_companies(user, "htq-holding") == []
