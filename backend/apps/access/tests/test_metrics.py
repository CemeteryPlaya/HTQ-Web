"""Задача 10 плана A: метрики аппки.

Метрики намеренно считают ПОПЕРЁК компаний (это их смысл — увидеть перекос по
всей группе), поэтому сторож из ``test_guards.py`` сканирует только
``services/`` и на ``metrics.py`` не распространяется.
"""

import pytest

from apps.access import metrics
from apps.access.models import (
    Level,
    PositionRole,
    Role,
    RoleAssignment,
    RoleModulePermission,
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
    Role.objects.create(code="empty", title="Пустая")
    useful = Role.objects.create(code="useful", title="Полезная")
    RoleModulePermission.objects.create(role=useful, module="hr", level=Level.READ)

    got = metrics.collect()
    assert got["access_roles_total"]["values"] == [((), 2)]
    assert got["access_roles_without_permissions"]["values"] == [((), 1)]


@pytest.mark.django_db
def test_admin_only_role_is_counted():
    all_admin = Role.objects.create(code="god", title="Всё")
    RoleModulePermission.objects.create(role=all_admin, module="hr", level=Level.ADMIN)
    RoleModulePermission.objects.create(role=all_admin, module="tasks", level=Level.ADMIN)
    mixed = Role.objects.create(code="mixed", title="Смешанная")
    RoleModulePermission.objects.create(role=mixed, module="hr", level=Level.ADMIN)
    RoleModulePermission.objects.create(role=mixed, module="tasks", level=Level.READ)

    assert metrics.collect()["access_roles_admin_only"]["values"] == [((), 1)]


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
