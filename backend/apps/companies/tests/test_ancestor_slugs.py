"""``companies.interface.ancestor_slugs`` — предки компании вверх по дереву
владения (задача 9.4, заготовка под B8.1 — кросс-компанейское согласование).

Правило обхода одно на платформу: ``access.services.inheritance.ancestors_of``
теперь зовёт эту функцию, поэтому её поведение — контракт для наследования
прав: от родителя вверх, архивные включены, цикл не вешает.
"""

import pytest

from apps.companies import interface
from apps.companies.models import Company, CompanyKind, CompanyStatus


def _co(slug, parent=None, **kw):
    return Company.objects.create(
        slug=slug, name=slug, kind=CompanyKind.SERVICE, parent=parent, **kw,
    )


@pytest.mark.django_db
def test_chain_goes_from_parent_upward():
    top = _co("t-anc-top")
    mid = _co("t-anc-mid", top)
    low = _co("t-anc-low", mid)
    _co("t-anc-leaf", low)

    assert interface.ancestor_slugs("t-anc-leaf") == [
        "t-anc-low", "t-anc-mid", "t-anc-top",
    ]
    assert interface.ancestor_slugs("t-anc-low") == ["t-anc-mid", "t-anc-top"]


@pytest.mark.django_db
def test_archived_intermediate_ancestor_is_included():
    """Архив обход не обрывает и из результата не выбрасывается: чьи роли
    и этапы действуют, решает вызывающий."""
    top = _co("t-anc-arch-top")
    mid = _co("t-anc-arch-mid", top, status=CompanyStatus.ARCHIVED)
    _co("t-anc-arch-low", mid)

    assert interface.ancestor_slugs("t-anc-arch-low") == [
        "t-anc-arch-mid", "t-anc-arch-top",
    ]


@pytest.mark.django_db
def test_cycle_does_not_hang_or_duplicate():
    """Цикл заводится мимо приложения — прямым UPDATE."""
    a = _co("t-anc-cyc-a")
    b = _co("t-anc-cyc-b", a)
    c = _co("t-anc-cyc-c", b)
    Company.objects.filter(pk=a.pk).update(parent=c)

    ancestors = interface.ancestor_slugs("t-anc-cyc-c")
    assert ancestors == ["t-anc-cyc-b", "t-anc-cyc-a"]
    assert "t-anc-cyc-c" not in ancestors
    assert len(ancestors) == len(set(ancestors))


@pytest.mark.django_db
def test_company_without_parent_has_no_ancestors():
    _co("t-anc-root")
    assert interface.ancestor_slugs("t-anc-root") == []


@pytest.mark.django_db
def test_unknown_slug_is_empty_list():
    assert interface.ancestor_slugs("t-anc-no-such-company") == []
