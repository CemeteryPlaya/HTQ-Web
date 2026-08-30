"""Задача 10 плана A: метрики аппки.

Метрики намеренно считают ПОПЕРЁК компаний (это их смысл — увидеть перекос по
всей группе), поэтому сторож из ``test_guards.py`` сканирует только
``services/`` и на ``metrics.py`` не распространяется.
"""

import pytest

from apps.access import metrics
from apps.access.tests.helpers import grant
from apps.access.models import (
    PositionRole,
    Role,
    RoleAssignment,
    ScopeKind,
)


@pytest.mark.django_db
def test_collect_returns_the_common_shape():
    """Форма та же, что у соседей: {имя: {help, labels?, values}}."""
    got = metrics.collect()
    for name, series in got.items():
        assert "help" in series, name
        assert isinstance(series["values"], list), name
        for labels, value in series["values"]:
            assert isinstance(labels, tuple), name
            assert isinstance(value, int), name
            assert len(labels) == len(series.get("labels", [])), name


@pytest.mark.django_db
def test_empty_role_is_counted():
    """Счёт ведётся от засеянного состояния: platform-admin есть в любой базе."""
    before = metrics.collect()["access_roles_total"]["values"][0][1]
    Role.objects.create(code="empty", title="Пустая")
    useful = Role.objects.create(code="useful", title="Полезная")
    grant(useful, "hr", "read")

    got = metrics.collect()
    assert got["access_roles_total"]["values"] == [((), before + 2)]
    assert got["access_roles_without_permissions"]["values"] == [((), 1)]


@pytest.mark.django_db
def test_roles_with_delete_are_counted():
    """Удаление — разрушающее право, и рост числа таких ролей стоит видеть."""
    destructive = Role.objects.create(code="god", title="Всё")
    grant(destructive, "hr", "full")
    harmless = Role.objects.create(code="mixed", title="Смешанная")
    grant(harmless, "hr", "edit")

    # Засеянная platform-admin тоже даёт удаление — считаем вместе с ней.
    assert metrics.collect()["access_roles_with_delete"]["values"] == [((), 2)]


@pytest.mark.django_db
def test_assignments_are_split_by_company():
    role = Role.objects.create(code="r", title="Роль")
    PositionRole.objects.create(company_slug="htq-kz", position_id=1, role=role)
    RoleAssignment.objects.create(company_slug="htq-kz", user_id=1, role=role,
                                  scope_kind=ScopeKind.COMPANY, scope_id=None)
    RoleAssignment.objects.create(company_slug="kurly-kg", user_id=1, role=role,
                                  scope_kind=ScopeKind.COMPANY, scope_id=None)

    got = metrics.collect()
    assert got["access_position_roles_by_company"]["values"] == [(("htq-kz",), 1)]
    assert got["access_personal_assignments_by_company"]["values"] == [
        (("htq-kz",), 1), (("kurly-kg",), 1),
    ]
