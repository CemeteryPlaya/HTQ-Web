"""Задача 4 плана A: разрешение прав по всем ветвям §1.5 спеки."""

import logging

import pytest

from apps.access.models import (
    Level,
    PositionRole,
    Role,
    RoleAssignment,
    RoleModulePermission,
    ScopeKind,
)
from apps.access.services import resolve

COMPANY = "htq-kz"


def _role(code: str, module: str, level: str) -> Role:
    role = Role.objects.create(code=code, title=code)
    RoleModulePermission.objects.create(role=role, module=module, level=level)
    return role


# ── Ветка 1: суперпользователь ────────────────────────────────────────────


@pytest.mark.django_db
def test_superuser_gets_admin_everywhere(superuser):
    assert resolve.permission_level(superuser, "hr", COMPANY) == Level.ADMIN
    assert resolve.permission_level(superuser, "tasks", COMPANY) == Level.ADMIN


# ── Ветка 2: нет контекста компании ───────────────────────────────────────


@pytest.mark.django_db
def test_no_company_context_means_no_rights(user):
    """Подстановка «по умолчанию» запрещена — спека §1.5, пункт 2."""
    assert resolve.permission_level(user, "hr", None) == Level.NONE
    assert resolve.permissions_for(user, None) == {}


# ── Ветка 3: роли должности и личные назначения ───────────────────────────


@pytest.mark.django_db
def test_position_roles_grant_rights(user, employee_with_position):
    role = _role("hr-read", "hr", Level.READ)
    PositionRole.objects.create(company_slug=COMPANY,
                                position_id=employee_with_position.id, role=role)
    assert resolve.permission_level(user, "hr", COMPANY) == Level.READ


@pytest.mark.django_db
def test_personal_assignment_grants_rights_without_employee(user):
    """Директор холдинга без кадровой карточки — спека §1.2."""
    role = _role("boss", "tasks", Level.ADMIN)
    RoleAssignment.objects.create(company_slug=COMPANY, user_id=user.id, role=role,
                                  scope_kind=ScopeKind.COMPANY, scope_id=None)
    assert resolve.permission_level(user, "tasks", COMPANY) == Level.ADMIN


@pytest.mark.django_db
def test_position_and_personal_roles_are_united(user, employee_with_position):
    position_role = _role("p-hr", "hr", Level.READ)
    PositionRole.objects.create(company_slug=COMPANY,
                                position_id=employee_with_position.id, role=position_role)
    personal_role = _role("u-tasks", "tasks", Level.WRITE)
    RoleAssignment.objects.create(company_slug=COMPANY, user_id=user.id,
                                  role=personal_role,
                                  scope_kind=ScopeKind.COMPANY, scope_id=None)

    perms = resolve.permissions_for(user, COMPANY)
    assert perms["hr"]["level"] == Level.READ
    assert perms["tasks"]["level"] == Level.WRITE


@pytest.mark.django_db
def test_max_level_wins_by_module(user):
    low = _role("low", "hr", Level.READ)
    high = _role("high", "hr", Level.ADMIN)
    for role in (low, high):
        RoleAssignment.objects.create(company_slug=COMPANY, user_id=user.id, role=role,
                                      scope_kind=ScopeKind.COMPANY, scope_id=None)
    assert resolve.permission_level(user, "hr", COMPANY) == Level.ADMIN


@pytest.mark.django_db
def test_widest_scope_of_the_winning_level(user):
    """Область — самая широкая ИЗ ТЕХ назначений, что дали этот уровень."""
    narrow = _role("narrow", "hr", Level.WRITE)
    RoleAssignment.objects.create(company_slug=COMPANY, user_id=user.id, role=narrow,
                                  scope_kind=ScopeKind.DEPARTMENT, scope_id=3)
    wide = _role("wide", "hr", Level.WRITE)
    RoleAssignment.objects.create(company_slug=COMPANY, user_id=user.id, role=wide,
                                  scope_kind=ScopeKind.COMPANY, scope_id=None)

    assert resolve.permissions_for(user, COMPANY)["hr"] == {
        "level": Level.WRITE, "scope": {"kind": ScopeKind.COMPANY, "id": None},
    }


@pytest.mark.django_db
def test_narrow_scope_of_a_higher_level_is_not_widened(user):
    """Более широкая область НИЖНЕГО уровня не должна расширять верхний."""
    wide_read = _role("wide-read", "hr", Level.READ)
    RoleAssignment.objects.create(company_slug=COMPANY, user_id=user.id, role=wide_read,
                                  scope_kind=ScopeKind.COMPANY, scope_id=None)
    narrow_admin = _role("narrow-admin", "hr", Level.ADMIN)
    RoleAssignment.objects.create(company_slug=COMPANY, user_id=user.id,
                                  role=narrow_admin,
                                  scope_kind=ScopeKind.DEPARTMENT, scope_id=3)

    assert resolve.permissions_for(user, COMPANY)["hr"] == {
        "level": Level.ADMIN, "scope": {"kind": ScopeKind.DEPARTMENT, "id": 3},
    }


# ── Ветка 4: изоляция компаний ────────────────────────────────────────────


@pytest.mark.django_db
def test_other_company_rights_are_invisible(user):
    """Изоляция держится фильтром по компании — спека §1.3, риск 3."""
    role = _role("foreign", "hr", Level.ADMIN)
    RoleAssignment.objects.create(company_slug="kurly-kg", user_id=user.id, role=role,
                                  scope_kind=ScopeKind.COMPANY, scope_id=None)
    assert resolve.permission_level(user, "hr", COMPANY) == Level.NONE


@pytest.mark.django_db
def test_position_roles_of_other_company_are_invisible(user, employee_with_position):
    role = _role("foreign-pos", "hr", Level.ADMIN)
    PositionRole.objects.create(company_slug="kurly-kg",
                                position_id=employee_with_position.id, role=role)
    assert resolve.permission_level(user, "hr", COMPANY) == Level.NONE


# ── Ветка 5: пусто ────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_modules_with_none_are_absent(user):
    role = _role("nothing", "hr", Level.NONE)
    RoleAssignment.objects.create(company_slug=COMPANY, user_id=user.id, role=role,
                                  scope_kind=ScopeKind.COMPANY, scope_id=None)
    perms = resolve.permissions_for(user, COMPANY)
    assert "hr" not in perms
    assert "mail" not in perms


@pytest.mark.django_db
def test_user_without_any_role_has_nothing(user):
    assert resolve.permissions_for(user, COMPANY) == {}


# ── Выключенный кадровый модуль ───────────────────────────────────────────


@pytest.mark.django_db
def test_disabled_hr_leaves_personal_assignments_and_logs_fallback(
        user, employee_with_position, service_off, caplog):
    """Выключенный кадровый модуль не должен молча обнулять права."""
    position_role = _role("p-hr", "hr", Level.ADMIN)
    PositionRole.objects.create(company_slug=COMPANY,
                                position_id=employee_with_position.id, role=position_role)
    personal = _role("u-tasks", "tasks", Level.READ)
    RoleAssignment.objects.create(company_slug=COMPANY, user_id=user.id, role=personal,
                                  scope_kind=ScopeKind.COMPANY, scope_id=None)

    with caplog.at_level(logging.INFO, logger="htqweb.fallback"):
        with service_off("hr"):
            perms = resolve.permissions_for(user, COMPANY)

    assert perms["tasks"]["level"] == Level.READ
    assert "hr" not in perms
    assert "FALLBACK" in caplog.text
    assert "access.resolve.hr_unavailable" in caplog.text
