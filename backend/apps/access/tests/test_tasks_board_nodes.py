"""Узлы досок задач (access/0028, канбан K1.2).

``tasks.departments.all`` — «Доски всех отделов»: ОД и ГД видят доски всех
отделов со всеми задачами. ``project.board`` открывает задачи внутри досок
проектов (а не только список досок, как раньше), поэтому выдаётся только явной
строкой и получает просмотр у ГД (решения заказчика 21.10, мастер-план K-11,
K-12, K-15). Оба узла ``EXPLICIT_ONLY``: широкая роль модуля без строки их не
наследует; явная строка — у каждой системной роли, кроме модульной
``platform-admin`` (приём ``access/0024``).
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

ALL_DEPTS = "tasks.departments.all"
BOARD = "project.board"
DIRECTORS = {"bpp-od", "bpp-gd"}
BOARD_VIEWERS = {"bpp-td", "bpp-od", "bpp-gd", "bpp-pm", "bpp-adm"}
COMPANY = "t-kanban-nodes"

migration = importlib.import_module("apps.access.migrations.0028_tasks_board_nodes")


def _system_roles():
    return Role.objects.filter(is_system=True).exclude(code="platform-admin")


def _rows(node: str) -> dict[str, set[str]]:
    return {row.role.code: set(row.flags)
            for row in RolePermission.objects.filter(node=node).select_related("role")}


@pytest.mark.django_db
def test_all_departments_row_at_every_system_role():
    rows = _rows(ALL_DEPTS)
    codes = {role.code for role in _system_roles()}
    assert DIRECTORS <= codes
    assert codes <= set(rows), sorted(codes - set(rows))
    for code in codes:
        assert rows[code] == ({"view"} if code in DIRECTORS else set()), code


@pytest.mark.django_db
def test_board_row_at_every_system_role():
    rows = _rows(BOARD)
    codes = {role.code for role in _system_roles()}
    assert codes <= set(rows), sorted(codes - set(rows))
    for code in codes:
        assert rows[code] == ({"view"} if code in BOARD_VIEWERS else set()), code


@pytest.mark.django_db
def test_platform_admin_has_no_rows_on_new_nodes():
    assert not RolePermission.objects.filter(
        role__code="platform-admin", node__in=(ALL_DEPTS, BOARD)).exists()


def test_both_nodes_explicit_only():
    assert {ALL_DEPTS, BOARD} <= registry.explicit_only()


def test_all_departments_node_is_registered_view_only():
    node = next(row for row in registry.nodes() if row["path"] == ALL_DEPTS)
    assert node["flags"] == ["view"]
    assert node.get("explicit_only") is True
    assert registry.is_known("tasks.departments")


@pytest.mark.django_db
def test_custom_role_with_tasks_full_lacks_all_departments():
    assign(COMPANY, 8101, "tasks", "full")
    user = SimpleNamespace(id=8101, is_superuser=False, email=None)
    assert resolve.permission_level(user, "tasks", COMPANY) == "admin"
    assert resolve.flags_for(user, ALL_DEPTS, COMPANY) == frozenset()


@pytest.mark.django_db
def test_custom_role_with_project_full_lacks_board():
    assign(COMPANY, 8102, "project", "full")
    user = SimpleNamespace(id=8102, is_superuser=False, email=None)
    assert resolve.permission_level(user, "project", COMPANY) == "admin"
    assert resolve.flags_for(user, BOARD, COMPANY) == frozenset()


@pytest.mark.django_db
def test_explicit_row_grants_the_node():
    assign(COMPANY, 8103, ALL_DEPTS, "view")
    user = SimpleNamespace(id=8103, is_superuser=False, email=None)
    assert "view" in resolve.flags_for(user, ALL_DEPTS, COMPANY)


@pytest.mark.django_db
def test_unseed_then_seed_is_idempotent():
    before_all, before_board = _rows(ALL_DEPTS), _rows(BOARD)
    migration.unseed(django_apps, SimpleNamespace())
    assert _rows(ALL_DEPTS) == {}
    assert _rows(BOARD)["bpp-gd"] == set()
    migration.seed(django_apps, SimpleNamespace())
    migration.seed(django_apps, SimpleNamespace())
    assert _rows(ALL_DEPTS) == before_all
    assert _rows(BOARD) == before_board


@pytest.mark.django_db
def test_seed_keeps_a_manual_board_row_of_a_non_bpp_role():
    """Не-``bpp`` роли строка ставится ``get_or_create``: выданный вручную
    просмотр доски повторный прогон миграции не затирает."""
    row = RolePermission.objects.get(role__code="hr-lead", node=BOARD)
    row.can_view = True
    row.save()
    migration.seed(django_apps, SimpleNamespace())
    assert _rows(BOARD)["hr-lead"] == {"view"}
