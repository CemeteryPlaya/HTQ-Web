"""Системные роли БЗО: существуют, системные, операции только у кого положено."""

import pytest

from apps.access.models import Role, RolePermission

ROLES = ("bpp-fd", "bpp-td", "bpp-od", "bpp-gd", "bpp-buh", "bpp-sn", "bpp-pm", "bpp-adm")
OPERATIONS = ("bpp.budgets.approve", "bpp.requests.cancel_approved",
              "bpp.agreements.terminate", "bpp.invoices.decision", "bpp.invoices.payment",
              "bpp.counterparties.block", "bpp.alternatives.select",
              "bpp.accountable.payment", "bpp.invoices.closing_docs")


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
def test_article_groups_split_supply_and_pm():
    assert "view" in _flags("bpp-sn", "bpp.articles.supply")
    assert _flags("bpp-sn", "bpp.articles.pm") == set()
    assert "view" in _flags("bpp-pm", "bpp.articles.pm")
    assert _flags("bpp-pm", "bpp.articles.supply") == set()
