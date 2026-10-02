"""Системные роли БЗО: существуют, системные, операции только у кого положено."""

import pytest

from apps.access.models import Role, RolePermission

ROLES = ("bpp-fd", "bpp-td", "bpp-od", "bpp-gd", "bpp-buh", "bpp-sn", "bpp-pm", "bpp-adm")
OPERATIONS = ("bpp.budgets.approve", "bpp.requests.cancel_approved",
              "bpp.agreements.terminate", "bpp.invoices.decision", "bpp.invoices.payment",
              "bpp.counterparties.block", "bpp.alternatives.select",
              "bpp.accountable.payment", "bpp.invoices.closing_docs",
              "project.all", "bpp.requests.all", "bpp.plan.reassign", "bpp.routes",
              "project.board", "bpp.invoices.all", "bpp.agreements.all", "bpp.accountable.all")


def _flags(code: str, node: str) -> set[str]:
    row = RolePermission.objects.get(role__code=code, node=node)
    return set(row.flags)


@pytest.mark.django_db
def test_every_bpp_role_exists_and_is_system():
    found = Role.objects.filter(code__in=ROLES)
    assert {r.code for r in found} == set(ROLES)
    assert all(r.is_system and not r.company_slug for r in found)


@pytest.mark.django_db
def test_every_role_has_an_explicit_row_on_every_operation():
    """Узел из трёх сегментов наследует глубину родителя: без явной строки
    автор счёта с edit на bpp.invoices получил бы решение ФД."""
    for code in ROLES:
        for node in OPERATIONS:
            assert RolePermission.objects.filter(role__code=code, node=node).exists(), \
                (code, node)


@pytest.mark.django_db
def test_only_fd_decides_on_invoices_and_only_buh_marks_payment():
    assert [c for c in ROLES if "edit" in _flags(c, "bpp.invoices.decision")] == ["bpp-fd"]
    assert [c for c in ROLES if "edit" in _flags(c, "bpp.invoices.payment")] == ["bpp-buh"]


@pytest.mark.django_db
def test_alternatives_are_chosen_by_fd_and_gd():
    chooser = [c for c in ROLES if "edit" in _flags(c, "bpp.alternatives.select")]
    assert chooser == ["bpp-fd", "bpp-gd"]


@pytest.mark.django_db
def test_only_pm_is_limited_to_his_projects():
    """Мастер-план A1.3: ПМ видит только проекты-участия (access/0015)."""
    assert [c for c in ROLES if "view" not in _flags(c, "project.all")] == ["bpp-pm"]


@pytest.mark.django_db
def test_article_groups_split_supply_and_pm():
    assert "view" in _flags("bpp-sn", "bpp.articles.supply")
    assert _flags("bpp-sn", "bpp.articles.pm") == set()
    assert "view" in _flags("bpp-pm", "bpp.articles.pm")
    assert _flags("bpp-pm", "bpp.articles.supply") == set()


@pytest.mark.django_db
def test_who_sees_all_requests_and_who_reassigns_plan_items():
    """Сверка B §7.3 (access/0017): те же роли, что до узлов — «просмотр
    заявок без создания» и ``edit`` на ``bpp.settings``."""
    assert [c for c in ROLES if "view" in _flags(c, "bpp.requests.all")] == [
        "bpp-fd", "bpp-td", "bpp-od", "bpp-gd", "bpp-adm"]
    assert [c for c in ROLES if "edit" in _flags(c, "bpp.plan.reassign")] == ["bpp-adm"]
    # Узлы несут ровно свой признак — ничего сверх.
    for code in ROLES:
        assert _flags(code, "bpp.requests.all") <= {"view"}, code
        assert _flags(code, "bpp.plan.reassign") <= {"edit"}, code


@pytest.mark.django_db
def test_routes_are_edited_by_fd_and_adm():
    """В-09 (access/0018): маршруты согласования модуля правят ФД и АДМ."""
    assert [c for c in ROLES if "edit" in _flags(c, "bpp.routes")] == ["bpp-fd", "bpp-adm"]
    for code in ROLES:
        assert _flags(code, "bpp.routes") <= {"edit"}, code


@pytest.mark.django_db
def test_gd_sees_every_section():
    """Решение 01.10 «ГД видит всё» (access/0019): план закупок целиком,
    подотчёт, выписки, настройки и закрывающие документы — только просмотр."""
    for node in ("bpp.plan", "bpp.plan.all", "bpp.accountable", "bpp.bank", "bpp.settings",
                 "bpp.invoices.closing_docs"):
        assert _flags("bpp-gd", node) == {"view"}, node


@pytest.mark.django_db
def test_board_link_is_for_td_od_pm_and_adm():
    """«Доска задач проекта» (access/0020): ссылка с «Проекта» и вход в доски
    задач — у ТД, ОД, ПМ и АДМ; у остальных явная пустая строка."""
    assert [c for c in ROLES if "view" in _flags(c, "project.board")] == [
        "bpp-td", "bpp-od", "bpp-pm", "bpp-adm"]
    for code in ROLES:
        assert _flags(code, "project.board") <= {"view"}, code


def test_only_fd_and_gd_see_all_plan_items():
    """I-2 итогового ревью: ``bpp.plan.all`` — explicit-only, строка у ФД и
    (решение 01.10 «ГД видит всё», access/0019) у ГД."""
    assert [c for c in ROLES if "view" in _flags(c, "bpp.plan.all")] == ["bpp-fd", "bpp-gd"]
    for code in ROLES:
        assert _flags(code, "bpp.plan.all") <= {"view"}, code


@pytest.mark.django_db
def test_who_sees_all_invoices_agreements_and_accountable():
    """D-S6-5 (access/0021): круг ролей прежней формулы «просмотр без
    создания», но узлом — СН, совмещающий ФД, не теряет чужие счета."""
    assert [c for c in ROLES if "view" in _flags(c, "bpp.invoices.all")] == [
        "bpp-fd", "bpp-td", "bpp-od", "bpp-gd", "bpp-buh"]
    assert [c for c in ROLES if "view" in _flags(c, "bpp.agreements.all")] == [
        "bpp-fd", "bpp-td", "bpp-od", "bpp-gd", "bpp-buh", "bpp-adm"]
    assert [c for c in ROLES if "view" in _flags(c, "bpp.accountable.all")] == [
        "bpp-fd", "bpp-buh"]
    for code in ROLES:
        for node in ("bpp.invoices.all", "bpp.agreements.all", "bpp.accountable.all"):
            assert _flags(code, node) <= {"view"}, (code, node)


ALL_NODES = (("bpp.invoices.all", "bpp.invoices"), ("bpp.agreements.all", "bpp.agreements"),
             ("bpp.accountable.all", "bpp.accountable"), ("bpp.requests.all", "bpp.requests"),
             ("bpp.plan.all", "bpp.plan"))


def _user_with(code: str, rows: dict[str, set[str]], user_id: int):
    from types import SimpleNamespace

    from apps.access.models import RoleAssignment, ScopeKind

    role = Role.objects.create(code=code, title=code)
    for node, flags in rows.items():
        RolePermission.objects.create(
            role=role, node=node, **{f"can_{f}": True for f in flags})
    RoleAssignment.objects.create(company_slug="htq-kz", user_id=user_id, role=role,
                                  scope_kind=ScopeKind.COMPANY, scope_id=None)
    return SimpleNamespace(id=user_id, is_superuser=False, email=None)


@pytest.mark.django_db
@pytest.mark.parametrize("all_node,parent", ALL_NODES)
def test_all_nodes_are_not_inherited_from_the_parent(all_node, parent):
    """Роль с view+create на документе (своя, из редактора) и «модульная»
    роль (как platform-admin, строка на ``bpp``) не видят чужие документы."""
    from apps.access.services import resolve

    own = _user_with("t-custom-own", {parent: {"view", "create"}}, 7001)
    module_wide = _user_with("t-module-bpp", {"bpp": {"view", "create", "edit", "delete"}}, 7002)
    for user in (own, module_wide):
        assert not resolve.can(user, all_node, "view", "htq-kz")
        assert "view" in resolve.flags_for(user, parent, "htq-kz")
    # Явная строка на самом узле — работает; уровень модуля не ломается.
    explicit = _user_with("t-explicit", {all_node: {"view"}}, 7003)
    assert resolve.can(explicit, all_node, "view", "htq-kz")
    assert resolve.permission_level(explicit, "bpp", "htq-kz") != "none"
    assert resolve.permission_level(module_wide, "bpp", "htq-kz") == "admin"


@pytest.mark.django_db
def test_superuser_sees_all_nodes():
    from types import SimpleNamespace

    from apps.access.services import resolve

    root = SimpleNamespace(id=7004, is_superuser=True, email=None)
    for all_node, _ in ALL_NODES:
        assert resolve.can(root, all_node, "view", "htq-kz")
