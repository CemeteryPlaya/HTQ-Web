"""Начальная раздача прав: засеянная роль и команда выдачи.

Проверяется выход из круга «чтобы выдать права, нужны права». Без него стадия
выкатывается с пустым каталогом, и все, кроме суперпользователя, теряют доступ
ко всем гейтованным разделам — включая тот, через который роли и выдаются.
"""

import pytest
from django.core.management import CommandError, call_command

from apps.access.models import Level, Role, RoleAssignment, RoleModulePermission, ScopeKind
from apps.access.services import resolve


@pytest.mark.django_db
def test_platform_admin_role_is_seeded():
    role = Role.objects.filter(code="platform-admin").first()
    assert role is not None, "миграция 0002 должна засеять роль-минимум"
    assert role.is_system is True


@pytest.mark.django_db
def test_seeded_role_grants_admin_on_every_module():
    from apps.core.models import KNOWN_SERVICES

    levels = dict(
        RoleModulePermission.objects
        .filter(role__code="platform-admin")
        .values_list("module", "level")
    )
    assert set(levels) == set(KNOWN_SERVICES)
    assert set(levels.values()) == {Level.ADMIN}


@pytest.mark.django_db
def test_grant_command_gives_working_rights(user):
    call_command("access_grant", "--user", user.username,
                 "--role", "platform-admin", "--company", "htq-kz")

    assert resolve.permission_level(user, "hr", "htq-kz") == Level.ADMIN
    assert resolve.permission_level(user, "access", "htq-kz") == Level.ADMIN


@pytest.mark.django_db
def test_grant_is_idempotent(user):
    for _ in range(2):
        call_command("access_grant", "--user", user.username,
                     "--role", "platform-admin", "--company", "htq-kz")

    assert RoleAssignment.objects.filter(user_id=user.id).count() == 1


@pytest.mark.django_db
def test_grant_does_not_leak_into_another_company(user):
    call_command("access_grant", "--user", user.username,
                 "--role", "platform-admin", "--company", "htq-kz")

    assert resolve.permission_level(user, "hr", "kurly-kg") == Level.NONE


@pytest.mark.django_db
def test_grant_accepts_user_id(user):
    call_command("access_grant", "--user", str(user.id),
                 "--role", "platform-admin", "--company", "htq-kz")

    assert RoleAssignment.objects.filter(user_id=user.id).exists()


@pytest.mark.django_db
def test_unknown_role_names_the_available_ones(user):
    with pytest.raises(CommandError) as exc:
        call_command("access_grant", "--user", user.username,
                     "--role", "нет-такой", "--company", "htq-kz")
    assert "platform-admin" in str(exc.value)


@pytest.mark.django_db
def test_unknown_user_is_refused():
    with pytest.raises(CommandError):
        call_command("access_grant", "--user", "нет-такого",
                     "--role", "platform-admin", "--company", "htq-kz")


@pytest.mark.django_db
def test_company_scope_rejects_scope_id(user):
    with pytest.raises(CommandError):
        call_command("access_grant", "--user", user.username, "--role", "platform-admin",
                     "--company", "htq-kz", "--scope-id", "3")


@pytest.mark.django_db
def test_department_scope_requires_scope_id(user):
    with pytest.raises(CommandError):
        call_command("access_grant", "--user", user.username, "--role", "platform-admin",
                     "--company", "htq-kz", "--scope", ScopeKind.DEPARTMENT)
