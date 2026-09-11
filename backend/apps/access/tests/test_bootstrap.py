"""Начальная раздача прав: засеянная роль и команда выдачи.

Проверяется выход из круга «чтобы выдать права, нужны права». Без него стадия
выкатывается с пустым каталогом, и все, кроме суперпользователя, теряют доступ
ко всем гейтованным разделам — включая тот, через который роли и выдаются.
"""

import pytest
from django.core.management import CommandError, call_command

from apps.access.models import Level, Role, RoleAssignment, RolePermission, ScopeKind
from apps.access import depth
from apps.access.services import resolve


@pytest.mark.django_db
def test_platform_admin_role_is_seeded():
    role = Role.objects.filter(code="platform-admin").first()
    assert role is not None, "миграция 0002 должна засеять роль-минимум"
    assert role.is_system is True


@pytest.mark.django_db
def test_seeded_role_grants_admin_on_every_module():
    from apps.core.models import KNOWN_SERVICES

    rows = {row.node: row.flags
            for row in RolePermission.objects.filter(role__code="platform-admin")}
    assert set(rows) == set(KNOWN_SERVICES)
    # Полный доступ на каждом модуле: все четыре признака глубины.
    assert all(flags == frozenset(depth.FLAGS) for flags in rows.values())


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


# ── Шаблон рядового сотрудника ──────────────────────────────────────────────


@pytest.mark.django_db
def test_employee_role_is_seeded_and_undeletable():
    role = Role.objects.filter(code="employee-basic").first()
    assert role is not None, "миграция 0004 должна засеять шаблон сотрудника"
    assert role.is_system is True


@pytest.mark.django_db
def test_employee_role_cannot_be_deleted():
    from apps.access.services import catalog
    from apps.access.services.errors import RoleIsSystem

    role = Role.objects.get(code="employee-basic")
    with pytest.raises(RoleIsSystem):
        catalog.delete_role(role.id)


@pytest.mark.django_db
def test_employee_role_matches_the_requested_set():
    """Состав продиктован заказчиком — проверяем его дословно."""
    from apps.access.services import catalog

    role = Role.objects.get(code="employee-basic")
    rows = {row["node"]: row["flags"] for row in catalog.permissions_of(role.id)}

    assert rows["users.profile"] == ["create", "edit", "view"]
    assert rows["messenger.chats"] == ["view"]
    assert rows["mail.messages"] == ["view"]
    assert rows["cms.news"] == ["view"]
    assert rows["tasks.tasks"] == ["create", "edit", "view"]
    assert rows["tasks.daily_reports"] == ["create", "view"]
    assert rows["tasks.calendar"] == ["create", "view"]
    assert rows["approvals.requests"] == ["create", "view"]
    assert rows["approvals.decisions"] == ["view"]
    assert rows["approvals.stats"] == ["view"]


@pytest.mark.django_db
def test_employee_may_join_a_conference_but_not_create_one():
    """«Только заходить, создавать запрещено» — двумя строками, а не одной."""
    from apps.access.services import catalog

    role = Role.objects.get(code="employee-basic")
    rows = {row["node"]: row["flags"] for row in catalog.permissions_of(role.id)}

    assert rows["conference.join"] == ["view"]
    # Пустой набор — ЯВНЫЙ запрет: без него участие в конференциях
    # унаследовалось бы на выдачу ссылок.
    assert rows["conference.invites"] == []


@pytest.mark.django_db
def test_employee_role_opens_the_expected_modules(user):
    """Проекция в уровни модулей: что рядовой реально увидит в интерфейсе."""
    from apps.access.models import RoleAssignment, ScopeKind
    from apps.access.services import resolve

    role = Role.objects.get(code="employee-basic")
    RoleAssignment.objects.create(company_slug="htq-kz", user_id=user.id, role=role,
                                  scope_kind=ScopeKind.COMPANY, scope_id=None)

    assert resolve.permission_level(user, "tasks", "htq-kz") == Level.WRITE
    assert resolve.permission_level(user, "cms", "htq-kz") == Level.READ
    assert resolve.permission_level(user, "messenger", "htq-kz") == Level.READ
    # Кадры рядовому не открываются вовсе.
    assert resolve.permission_level(user, "hr", "htq-kz") == Level.NONE


@pytest.mark.django_db
def test_employee_role_can_be_copied_into_a_variation():
    """Шаблон неудаляем, но копируем — именно так и делают роль-вариацию."""
    from apps.access.services import catalog

    source = Role.objects.get(code="employee-basic")
    clone = catalog.copy_role(source.id, "employee-plus", "Сотрудник +")

    assert clone.is_system is False
    assert catalog.permissions_of(clone.id) == catalog.permissions_of(source.id)
