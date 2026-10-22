"""Роли и узлы тендерного модуля (T0.3; план этапов 0–2, §1).

Матрица «роль × узел» проверяется по КАЖДОЙ паре дословно: пустая строка —
явный запрет, а не пробел. Узлы «все документы» и операции выбора —
``EXPLICIT_ONLY``: роль с правами на весь модуль (кастомная, ``platform-admin``)
без явной строки их не получает.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from django.core.management import call_command

from apps.access import registry
from apps.access.models import PositionRole, Role, RoleAssignment, RolePermission, ScopeKind
from apps.access.services import resolve

V, C, E, D = "view", "create", "edit", "delete"
COMPANY = "htq-kz"

ROLES = ("tender-buyer", "tender-quality", "tender-fd", "tender-viewer", "tender-adm")

#: План этапов 0–2, §1 — дословно. Отсутствие узла у роли = пустая строка.
MATRIX: dict[str, dict[str, set[str]]] = {
    "tender-buyer": {
        "tender": {V, C, E, D}, "tender.requests": {V, C, E, D},
        "tender.tenders": {V, C, E, D}, "tender.prospects": {V, C, E},
        "tender.receipts": {V, C, E},
    },
    "tender-quality": {
        "tender": {V}, "tender.tenders": {V}, "tender.tenders.all": {V},
        "tender.award.quality": {E},
    },
    "tender-fd": {
        "tender": {V}, "tender.requests": {V}, "tender.requests.all": {V},
        "tender.tenders": {V}, "tender.tenders.all": {V}, "tender.award.approve": {E},
        "tender.prospects": {V}, "tender.receipts": {V}, "tender.settings": {V},
    },
    "tender-viewer": {
        "tender": {V}, "tender.requests": {V}, "tender.requests.all": {V},
        "tender.tenders": {V}, "tender.tenders.all": {V}, "tender.prospects": {V},
        "tender.receipts": {V},
    },
    "tender-adm": {
        "tender": {V, C, E, D}, "tender.requests": {V, C, E, D}, "tender.requests.all": {V},
        "tender.tenders": {V, C, E, D}, "tender.tenders.all": {V},
        "tender.prospects": {V, C, E, D}, "tender.receipts": {V, C, E},
        "tender.settings": {V, E},
    },
}

NODES = ("tender", "tender.requests", "tender.requests.all", "tender.tenders",
         "tender.tenders.all", "tender.award.quality", "tender.award.approve",
         "tender.prospects", "tender.receipts", "tender.settings")
EXPLICIT = {"tender.requests.all", "tender.tenders.all", "tender.award.quality",
            "tender.award.approve"}

#: Узлы ``EXPLICIT_ONLY`` соседей, у которых явная строка стоит у КАЖДОЙ
#: системной роли (access/0022, 0024, 0025) — новые роли не исключение.
FOREIGN_EXPLICIT = ("refdata.production_calendar", "project.structure", "project.roles",
                    "bpp.entry")


def _flags(code: str, node: str) -> set[str]:
    return set(RolePermission.objects.get(role__code=code, node=node).flags)


def _holder(code: str, user_id: int) -> SimpleNamespace:
    RoleAssignment.objects.create(company_slug=COMPANY, user_id=user_id,
                                  role=Role.objects.get(code=code),
                                  scope_kind=ScopeKind.COMPANY, scope_id=None)
    return SimpleNamespace(id=user_id, is_superuser=False, email=None)


# ── реестр ─────────────────────────────────────────────────────────────────

def test_nodes_are_declared_with_their_flags():
    rows = {row["path"]: set(row["flags"]) for row in registry.nodes()}
    assert rows["tender.requests"] == {V, C, E, D}
    assert rows["tender.tenders"] == {V, C, E, D}
    assert rows["tender.prospects"] == {V, C, E, D}
    assert rows["tender.requests.all"] == {V}
    assert rows["tender.tenders.all"] == {V}
    assert rows["tender.award.quality"] == {E}
    assert rows["tender.award.approve"] == {E}
    assert rows["tender.receipts"] == {V, C, E}
    assert rows["tender.settings"] == {V, E}


def test_all_and_award_nodes_are_explicit_only():
    only = registry.explicit_only()
    assert EXPLICIT <= only
    assert not {n for n in only if n.startswith("tender.")} - EXPLICIT


def test_no_orphan_node_in_the_tree():
    """У операций выбора есть родитель ``tender.award`` — иначе редактор ролей
    показал бы поле корнем дерева рядом с модулями."""
    paths = {row["path"] for row in registry.nodes()}
    for path in paths:
        if path.startswith("tender.") and path.count(".") == 2:
            assert path.rsplit(".", 1)[0] in paths, path


# ── роли ───────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_every_tender_role_exists_and_is_system():
    found = Role.objects.filter(code__in=ROLES)
    assert {r.code for r in found} == set(ROLES)
    assert all(r.is_system and not r.company_slug for r in found)


@pytest.mark.django_db
@pytest.mark.parametrize("code", ROLES)
@pytest.mark.parametrize("node", NODES)
def test_role_node_pair_is_explicit_and_exact(code, node):
    row = RolePermission.objects.filter(role__code=code, node=node).first()
    assert row is not None, f"нет явной строки {code} × {node}"
    assert set(row.flags) == MATRIX[code].get(node, set())


@pytest.mark.django_db
@pytest.mark.parametrize("code", ROLES)
@pytest.mark.parametrize("node", NODES)
def test_resolver_gives_exactly_the_matrix(code, node):
    """Глубина у держателя роли — ровно матрица: наследование от модуля ничего
    не добавляет ни операциям выбора, ни «всем документам»."""
    user = _holder(code, 8100 + ROLES.index(code))
    assert set(resolve.flags_for(user, node, COMPANY)) == MATRIX[code].get(node, set())


@pytest.mark.django_db
def test_only_td_checks_quality_and_only_fd_approves():
    assert [c for c in ROLES if E in _flags(c, "tender.award.quality")] == ["tender-quality"]
    assert [c for c in ROLES if E in _flags(c, "tender.award.approve")] == ["tender-fd"]


@pytest.mark.django_db
def test_other_system_roles_carry_an_empty_row_on_explicit_nodes():
    """Приём access/0022–0025: явная пустая строка у каждой системной роли,
    кроме модульной ``platform-admin``."""
    others = Role.objects.filter(is_system=True).exclude(code__in=(*ROLES, "platform-admin"))
    assert others.exists()
    for role in others:
        for node in EXPLICIT:
            row = RolePermission.objects.filter(role=role, node=node).first()
            assert row is not None, (role.code, node)
            assert set(row.flags) == set(), (role.code, node)
    assert not RolePermission.objects.filter(role__code="platform-admin",
                                             node__in=EXPLICIT).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("code", ROLES)
def test_tender_roles_carry_empty_rows_on_foreign_explicit_nodes(code):
    for node in FOREIGN_EXPLICIT:
        row = RolePermission.objects.filter(role__code=code, node=node).first()
        assert row is not None, (code, node)
        assert set(row.flags) == set(), (code, node)


@pytest.mark.django_db
def test_module_wide_role_without_rows_sees_no_all_and_decides_nothing():
    role = Role.objects.create(code="t-tender-module", title="t")
    RolePermission.objects.create(role=role, node="tender", can_view=True, can_create=True,
                                  can_edit=True, can_delete=True)
    RoleAssignment.objects.create(company_slug=COMPANY, user_id=8200, role=role,
                                  scope_kind=ScopeKind.COMPANY, scope_id=None)
    user = SimpleNamespace(id=8200, is_superuser=False, email=None)
    assert resolve.permission_level(user, "tender", COMPANY) == "admin"
    assert V in resolve.flags_for(user, "tender.requests", COMPANY)
    for node in EXPLICIT:
        assert resolve.flags_for(user, node, COMPANY) == frozenset(), node


@pytest.mark.django_db
def test_platform_admin_does_not_see_all_documents():
    user = _holder("platform-admin", 8201)
    assert resolve.permission_level(user, "tender", COMPANY) == "admin"
    assert not resolve.can(user, "tender.requests.all", V, COMPANY)
    assert not resolve.can(user, "tender.award.approve", E, COMPANY)


@pytest.mark.django_db
@pytest.mark.parametrize("code,level", [("tender-buyer", "admin"), ("tender-quality", "write"),
                                        ("tender-fd", "write"), ("tender-viewer", "read"),
                                        ("tender-adm", "admin")])
def test_module_level_of_each_role(code, level):
    """Гейт ручек: чтение — ``read``, запись — ``write``. У проверяющего
    качество и ФД запись — их операции выбора (edit на узле-операции)."""
    user = _holder(code, 8300 + ROLES.index(code))
    assert resolve.permission_level(user, "tender", COMPANY) == level


# ── tender_assign_roles ────────────────────────────────────────────────────

@pytest.fixture
def staff(company_context):
    from apps.hr.models import Department, Position

    dep = Department.objects.create(name="Дирекция", path="dir")
    made = {}
    for title, weight in (("Менеджер по закупкам", 500), ("Руководитель проекта", 400),
                          ("Технический директор", 120), ("Финансовый директор", 110),
                          ("Главный бухгалтер", 610), ("Операционный директор", 130)):
        made[title] = Position.objects.create(title=title, department=dep, weight=weight)
    return made


@pytest.mark.django_db
def test_assign_roles_gives_positions_their_roles(company_context, staff, capsys):
    call_command("tender_assign_roles", "--company", company_context["slug"])
    given = set(PositionRole.objects.filter(role__code__startswith="tender-")
                .values_list("position_id", "role__code"))
    assert given == {
        (staff["Менеджер по закупкам"].id, "tender-buyer"),
        (staff["Руководитель проекта"].id, "tender-buyer"),
        (staff["Технический директор"].id, "tender-quality"),
        (staff["Финансовый директор"].id, "tender-fd"),
        (staff["Главный бухгалтер"].id, "tender-viewer"),
        (staff["Операционный директор"].id, "tender-viewer"),
    }
    assert not PositionRole.objects.filter(role__code="tender-adm").exists()
    out = capsys.readouterr().out
    assert "нет должности: Бухгалтер" in out


@pytest.mark.django_db
def test_assign_roles_is_idempotent(company_context, staff, capsys):
    call_command("tender_assign_roles", "--company", company_context["slug"])
    before = PositionRole.objects.filter(role__code__startswith="tender-").count()
    capsys.readouterr()
    call_command("tender_assign_roles", "--company", company_context["slug"])
    assert PositionRole.objects.filter(role__code__startswith="tender-").count() == before
    assert "уже есть: tender-fd → Финансовый директор" in capsys.readouterr().out


@pytest.mark.django_db
def test_assign_roles_dry_run_writes_nothing(company_context, staff, capsys):
    call_command("tender_assign_roles", "--company", company_context["slug"], "--dry-run")
    assert not PositionRole.objects.filter(role__code__startswith="tender-").exists()
    assert "выдать tender-fd → Финансовый директор" in capsys.readouterr().out
