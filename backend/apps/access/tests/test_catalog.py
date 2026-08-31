"""Задача 6 плана A: каталог ролей — операции платформенного уровня."""

import pytest

from apps.access.models import (
    Level,
    RolePermission,
    PositionRole,
    Role,
    RoleAssignment,
    ScopeKind,
)
from apps.access.tests.helpers import grant
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
    renamed = catalog.rename_role(role.id, title="Новое")
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
    catalog.set_permissions(role.id, [{"node": "hr", "preset": "edit"},
                                      {"node": "tasks", "preset": "view"}])
    catalog.set_permissions(role.id, [{"node": "hr", "preset": "view"}])
    rows = {row.node: row.flags for row in RolePermission.objects.filter(role=role)}
    assert rows == {"hr": frozenset({"view"})}


@pytest.mark.django_db
def test_none_is_stored_as_an_explicit_ban():
    """Пустой набор — это ЗАПРЕТ, а не «строки нет».

    Разница появилась вместе с наследованием: отсутствие строки означает
    «наследовать от предка», а пустой набор — перекрыть унаследованное. Слить их
    обратно значило бы лишить возможности закрыть одно поле внутри разрешённого
    модуля — ровно то, ради чего третий уровень и заведён.
    """
    role = catalog.create_role("r2", "Роль")
    catalog.set_permissions(role.id, [{"node": "hr.employees.salary", "preset": "none"}])
    row = RolePermission.objects.get(role=role)
    assert row.node == "hr.employees.salary"
    assert row.flags == frozenset()


@pytest.mark.django_db
def test_unknown_node_is_rejected():
    role = catalog.create_role("r3", "Роль")
    with pytest.raises(UnknownModule):
        catalog.set_permissions(role.id, [{"node": "нет-такого", "preset": "view"}])


@pytest.mark.django_db
def test_rejected_set_leaves_the_previous_one_intact():
    """Замена целиком обязана быть транзакционной, иначе отказ обнуляет права."""
    role = catalog.create_role("r4", "Роль")
    catalog.set_permissions(role.id, [{"node": "hr", "preset": "edit"}])
    with pytest.raises(UnknownModule):
        catalog.set_permissions(role.id, [{"node": "hr", "preset": "view"},
                                          {"node": "выдумка", "preset": "view"}])
    rows = {row.node: row.flags for row in RolePermission.objects.filter(role=role)}
    assert rows == {"hr": frozenset({"view", "create", "edit"})}


@pytest.mark.django_db
def test_permissions_of_a_role_are_readable():
    role = catalog.create_role("r5", "Роль")
    catalog.set_permissions(role.id, [{"node": "hr", "preset": "full"}])
    assert catalog.permissions_of(role.id) == [
        {"node": "hr", "flags": ["create", "delete", "edit", "view"], "preset": "full"},
    ]


# ── Переименование ──────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_rename_changes_the_code_too():
    """Без этого копия навсегда осталась бы «<исходный>-copy»."""
    role = catalog.create_role("old-code", "Старое")

    renamed = catalog.rename_role(role.id, title="Новое", code="new-code")

    assert (renamed.code, renamed.title) == ("new-code", "Новое")


@pytest.mark.django_db
def test_rename_accepts_only_one_field():
    role = catalog.create_role("keep-code", "Старое")

    catalog.rename_role(role.id, title="Только название")
    role.refresh_from_db()

    assert (role.code, role.title) == ("keep-code", "Только название")


@pytest.mark.django_db
def test_rename_to_a_taken_code_is_a_conflict():
    catalog.create_role("taken", "Занятая")
    role = catalog.create_role("free", "Свободная")

    with pytest.raises(RoleConflict):
        catalog.rename_role(role.id, code="taken")


@pytest.mark.django_db
def test_system_role_keeps_its_code():
    """Миграции находят засеянные роли по коду — сменив его, получим дубль."""
    from apps.access.services.errors import SystemRoleCodeLocked

    role = Role.objects.get(code="platform-admin")
    with pytest.raises(SystemRoleCodeLocked):
        catalog.rename_role(role.id, code="something-else")


@pytest.mark.django_db
def test_system_role_can_still_be_retitled():
    role = Role.objects.get(code="platform-admin")

    catalog.rename_role(role.id, title="Администратор платформы (главный)")
    role.refresh_from_db()

    assert role.title == "Администратор платформы (главный)"
    assert role.code == "platform-admin"


@pytest.mark.django_db
def test_rename_without_changes_is_a_noop():
    role = catalog.create_role("same", "Одинаковое")

    assert catalog.rename_role(role.id, title="Одинаковое", code="same").id == role.id
