"""Задача 2 плана A: модели каталога, привязок и назначений.

Каждый тест, ожидающий ``IntegrityError``, делает РОВНО одну такую проверку:
ошибка ограничения переводит транзакцию Postgres в aborted-состояние, где любой
следующий запрос запрещён до отката. Тот же приём, что в
``apps/companies/tests/test_models.py::test_slug_is_unique``.
"""

import pytest
from django.db import IntegrityError

from apps.access.models import (
    LEVEL_ORDER,
    Level,
    PositionRole,
    Role,
    RoleAssignment,
    RoleModulePermission,
    ScopeKind,
)


@pytest.mark.django_db
def test_role_code_is_unique_platform_wide():
    """Каталог один на все компании — код уникален глобально (спека §4.1)."""
    Role.objects.create(code="hr-admin", title="Кадровик")
    with pytest.raises(IntegrityError):
        Role.objects.create(code="hr-admin", title="Дубль")


@pytest.mark.django_db
def test_role_module_pair_is_unique():
    role = Role.objects.create(code="r0", title="Роль")
    RoleModulePermission.objects.create(role=role, module="hr", level=Level.READ)
    with pytest.raises(IntegrityError):
        RoleModulePermission.objects.create(role=role, module="hr", level=Level.WRITE)


@pytest.mark.django_db
def test_company_scope_forbids_scope_id():
    role = Role.objects.create(code="r1", title="Роль")
    with pytest.raises(IntegrityError):
        RoleAssignment.objects.create(
            company_slug="htq-kz", user_id=1, role=role,
            scope_kind=ScopeKind.COMPANY, scope_id=7,
        )


@pytest.mark.django_db
def test_department_scope_requires_scope_id():
    role = Role.objects.create(code="r2", title="Роль")
    with pytest.raises(IntegrityError):
        RoleAssignment.objects.create(
            company_slug="htq-kz", user_id=1, role=role,
            scope_kind=ScopeKind.DEPARTMENT, scope_id=None,
        )


@pytest.mark.django_db
def test_same_unscoped_assignment_twice_is_rejected():
    """NULL в scope_id не должен обходить уникальность (частичные индексы)."""
    role = Role.objects.create(code="r3", title="Роль")
    RoleAssignment.objects.create(company_slug="htq-kz", user_id=1, role=role,
                                  scope_kind=ScopeKind.COMPANY, scope_id=None)
    with pytest.raises(IntegrityError):
        RoleAssignment.objects.create(company_slug="htq-kz", user_id=1, role=role,
                                      scope_kind=ScopeKind.COMPANY, scope_id=None)


@pytest.mark.django_db
def test_same_scoped_assignment_twice_is_rejected():
    role = Role.objects.create(code="r4", title="Роль")
    RoleAssignment.objects.create(company_slug="htq-kz", user_id=1, role=role,
                                  scope_kind=ScopeKind.DEPARTMENT, scope_id=3)
    with pytest.raises(IntegrityError):
        RoleAssignment.objects.create(company_slug="htq-kz", user_id=1, role=role,
                                      scope_kind=ScopeKind.DEPARTMENT, scope_id=3)


@pytest.mark.django_db
def test_same_assignment_in_another_company_is_allowed():
    """Компания — часть ключа: одна и та же роль выдаётся в разных компаниях."""
    role = Role.objects.create(code="r5", title="Роль")
    RoleAssignment.objects.create(company_slug="htq-kz", user_id=1, role=role,
                                  scope_kind=ScopeKind.COMPANY, scope_id=None)
    RoleAssignment.objects.create(company_slug="kurly-kg", user_id=1, role=role,
                                  scope_kind=ScopeKind.COMPANY, scope_id=None)
    assert RoleAssignment.objects.filter(user_id=1).count() == 2


@pytest.mark.django_db
def test_same_position_role_twice_is_rejected():
    role = Role.objects.create(code="r6", title="Роль")
    PositionRole.objects.create(company_slug="htq-kz", position_id=5, role=role)
    with pytest.raises(IntegrityError):
        PositionRole.objects.create(company_slug="htq-kz", position_id=5, role=role)


@pytest.mark.django_db
def test_same_position_id_in_another_company_is_a_different_position():
    """id должностей нумеруются в каждой схеме независимо — они не пересекаются."""
    role = Role.objects.create(code="r7", title="Роль")
    PositionRole.objects.create(company_slug="htq-kz", position_id=5, role=role)
    PositionRole.objects.create(company_slug="kurly-kg", position_id=5, role=role)
    assert PositionRole.objects.filter(position_id=5).count() == 2


def test_level_order_is_total():
    assert [LEVEL_ORDER[v] for v in (Level.NONE, Level.READ, Level.WRITE, Level.ADMIN)] == [0, 1, 2, 3]


def test_models_do_not_reference_neighbours_by_foreign_key():
    """Межаппных FK у платформы нет — ни на компанию, ни на должность, ни на учётку."""
    from apps.access import models

    for model in (Role, RoleModulePermission, PositionRole, RoleAssignment):
        for field in model._meta.get_fields():
            if field.is_relation and field.many_to_one:
                assert field.related_model._meta.app_label == "access", (
                    f"{model.__name__}.{field.name} ссылается на чужую аппку"
                )
    assert models is not None
