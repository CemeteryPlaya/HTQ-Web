"""Узел ``tasks.boards.admin`` (access/0029, канбан-доски, решение K-39).

«Доски: настройки, поля и автоматизация» любой доски. Свою доску без узла
правят глава отдела и владелец проекта задач, поэтому по умолчанию узла нет ни
у одной системной роли: явная пустая строка у каждой, кроме модульной
``platform-admin`` (приём ``access/0028``). Узел ``EXPLICIT_ONLY``: роль с
``tasks:admin`` без строки его не наследует.
"""

from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest
from django.apps import apps as django_apps

from apps.access import registry
from apps.access.models import Role, RolePermission
from apps.access.services import resolve
from apps.access.tests.helpers import assign

NODE = "tasks.boards.admin"
COMPANY = "t-boards-admin"

migration = importlib.import_module("apps.access.migrations.0029_tasks_boards_admin")


def _system_roles():
    return Role.objects.filter(is_system=True).exclude(code="platform-admin")


@pytest.mark.django_db
def test_empty_row_at_every_system_role():
    rows = {row.role.code: set(row.flags)
            for row in RolePermission.objects.filter(node=NODE).select_related("role")}
    codes = {role.code for role in _system_roles()}
    assert codes and codes <= set(rows), sorted(codes - set(rows))
    assert all(rows[code] == set() for code in codes)
    assert "platform-admin" not in rows


def test_node_is_registered_explicit_only_edit():
    node = next(row for row in registry.nodes() if row["path"] == NODE)
    assert node["flags"] == ["edit"]
    assert node.get("explicit_only") is True
    assert NODE in registry.explicit_only()
    assert registry.is_known("tasks.boards")


@pytest.mark.django_db
def test_tasks_admin_role_does_not_inherit_the_node():
    assign(COMPANY, 8201, "tasks", "full")
    user = SimpleNamespace(id=8201, is_superuser=False, email=None)
    assert resolve.permission_level(user, "tasks", COMPANY) == "admin"
    assert resolve.flags_for(user, NODE, COMPANY) == frozenset()


@pytest.mark.django_db
def test_explicit_row_grants_the_node():
    assign(COMPANY, 8202, NODE, "edit")
    user = SimpleNamespace(id=8202, is_superuser=False, email=None)
    assert "edit" in resolve.flags_for(user, NODE, COMPANY)


@pytest.mark.django_db
def test_seed_keeps_a_manual_grant_and_unseed_keeps_it_too():
    role = _system_roles().first()
    RolePermission.objects.filter(role=role, node=NODE).update(can_edit=True)
    migration.seed(django_apps, SimpleNamespace())
    assert RolePermission.objects.get(role=role, node=NODE).can_edit is True
    migration.unseed(django_apps, SimpleNamespace())
    assert RolePermission.objects.filter(node=NODE).count() == 1
    migration.seed(django_apps, SimpleNamespace())
    assert set(RolePermission.objects.filter(node=NODE)
               .values_list("role__code", flat=True)) == {r.code for r in _system_roles()}
