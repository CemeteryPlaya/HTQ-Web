"""Узлы проектной структуры (access/0024, PS-9): явная строка у каждой
системной роли, правка — ровно у шести, глубину от ``project`` не берут."""

from types import SimpleNamespace

import pytest

from apps.access import registry
from apps.access.models import Role, RolePermission
from apps.access.services import resolve
from apps.access.tests.helpers import assign

NODES = ("project.structure", "project.roles")
EDITORS = {"bpp-fd", "bpp-td", "bpp-od", "bpp-gd", "bpp-adm", "hr-lead"}


@pytest.mark.django_db
def test_every_system_role_has_explicit_rows_and_only_six_edit():
    roles = Role.objects.filter(is_system=True).exclude(code="platform-admin")
    assert EDITORS <= {r.code for r in roles}
    for role in roles:
        for node in NODES:
            row = RolePermission.objects.get(role=role, node=node)
            expected = {"edit"} if role.code in EDITORS else set()
            assert set(row.flags) == expected, (role.code, node)
    assert not RolePermission.objects.filter(role__code="platform-admin",
                                             node__in=NODES).exists()


def test_nodes_are_explicit_only():
    assert set(NODES) <= registry.explicit_only()


@pytest.mark.django_db
def test_module_admin_without_row_does_not_edit_structure():
    assign("htq-kz", 7, "project", "admin")
    user = SimpleNamespace(id=7, is_superuser=False, email=None)
    assert resolve.permission_level(user, "project", "htq-kz") == "admin"
    for node in NODES:
        assert "edit" not in resolve.flags_for(user, node, "htq-kz")
    assign("htq-kz", 8, "project.structure", "edit")
    explicit = SimpleNamespace(id=8, is_superuser=False, email=None)
    assert "edit" in resolve.flags_for(explicit, "project.structure", "htq-kz")
    assert resolve.permission_level(explicit, "project", "htq-kz") == "write"
