"""Задача 6 плана A: каталог ролей — операции платформенного уровня."""

import pytest

from apps.access.models import (
    Level,
    PositionRole,
    Role,
    RoleAssignment,
    RoleModulePermission,
    ScopeKind,
)
from apps.access.services import catalog
from apps.access.services.errors import (
    RoleConflict,
    RoleInUse,
    RoleIsSystem,
    UnknownModule,
)


@pytest.mark.django_db
def test_create_role():
    role = catalog.create_role("hr-admin", "Администратор кадров")
    assert role.id and role.code == "hr-admin" and role.is_system is False


@pytest.mark.django_db
def test_duplicate_code_is_a_conflict():
    catalog.create_role("hr-admin", "Первый")
    with pytest.raises(RoleConflict):
        catalog.create_role("hr-admin", "Второй")


@pytest.mark.django_db
def test_rename_keeps_the_code():
    role = catalog.create_role("hr-admin", "Старое")
    renamed = catalog.rename_role(role.id, "Новое")
    assert (renamed.code, renamed.title) == ("hr-admin", "Новое")


@pytest.mark.django_db
def test_delete_removes_an_unused_role():
    role = catalog.create_role("temp", "Временная")
    catalog.delete_role(role.id)
    assert not Role.objects.filter(id=role.id).exists()


@pytest.mark.django_db
def test_delete_refuses_when_assigned_to_a_position():
    """Молчаливое снятие прав у неизвестного числа людей недопустимо."""
    role = catalog.create_role("used", "Занятая")
    PositionRole.objects.create(company_slug="htq-kz", position_id=1, role=role)
    with pytest.raises(RoleInUse) as exc:
        catalog.delete_role(role.id)
    assert (exc.value.positions, exc.value.users) == (1, 0)


@pytest.mark.django_db
def test_delete_refuses_when_assigned_to_a_user():
    role = catalog.create_role("used2", "Занятая")
    RoleAssignment.objects.create(company_slug="htq-kz", user_id=1, role=role,
                                  scope_kind=ScopeKind.COMPANY, scope_id=None)
    with pytest.raises(RoleInUse) as exc:
        catalog.delete_role(role.id)
    assert (exc.value.positions, exc.value.users) == (0, 1)


@pytest.mark.django_db
def test_delete_counts_use_across_all_companies():
    """Каталог общий: занятость считается по всей платформе, не по компании."""
    role = catalog.create_role("used3", "Занятая")
    PositionRole.objects.create(company_slug="htq-kz", position_id=1, role=role)
    PositionRole.objects.create(company_slug="kurly-kg", position_id=1, role=role)
    with pytest.raises(RoleInUse) as exc:
        catalog.delete_role(role.id)
    assert exc.value.positions == 2


@pytest.mark.django_db
def test_delete_refuses_system_role():
    role = Role.objects.create(code="sys", title="Системная", is_system=True)
    with pytest.raises(RoleIsSystem):
        catalog.delete_role(role.id)


@pytest.mark.django_db
def test_set_permissions_replaces_whole_set():
    """Отсутствующий в списке модуль становится none — спека §4.2."""
    role = catalog.create_role("r", "Роль")
    catalog.set_permissions(role.id, [{"module": "hr", "level": Level.WRITE},
                                      {"module": "tasks", "level": Level.READ}])
    catalog.set_permissions(role.id, [{"module": "hr", "level": Level.READ}])
    rows = {p.module: p.level for p in RoleModulePermission.objects.filter(role=role)}
    assert rows == {"hr": Level.READ}


@pytest.mark.django_db
def test_set_permissions_does_not_store_none():
    """Явный none и отсутствие модуля — одно и то же, хранить нечего."""
    role = catalog.create_role("r2", "Роль")
    catalog.set_permissions(role.id, [{"module": "hr", "level": Level.NONE}])
    assert not RoleModulePermission.objects.filter(role=role).exists()


@pytest.mark.django_db
def test_unknown_module_is_rejected():
    role = catalog.create_role("r3", "Роль")
    with pytest.raises(UnknownModule):
        catalog.set_permissions(role.id, [{"module": "нет-такого", "level": Level.READ}])


@pytest.mark.django_db
def test_rejected_set_leaves_the_previous_one_intact():
    """Замена целиком обязана быть транзакционной, иначе отказ обнуляет права."""
    role = catalog.create_role("r4", "Роль")
    catalog.set_permissions(role.id, [{"module": "hr", "level": Level.WRITE}])
    with pytest.raises(UnknownModule):
        catalog.set_permissions(role.id, [{"module": "hr", "level": Level.READ},
                                          {"module": "выдумка", "level": Level.READ}])
    rows = {p.module: p.level for p in RoleModulePermission.objects.filter(role=role)}
    assert rows == {"hr": Level.WRITE}


@pytest.mark.django_db
def test_permissions_of_a_role_are_readable():
    role = catalog.create_role("r5", "Роль")
    catalog.set_permissions(role.id, [{"module": "hr", "level": Level.ADMIN}])
    assert catalog.permissions_of(role.id) == [{"module": "hr", "level": Level.ADMIN}]
