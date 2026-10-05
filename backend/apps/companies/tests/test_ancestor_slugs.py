"""``companies.interface.ancestor_slugs`` — предки компании вверх по дереву
владения (задача 9.4 и B8.1; две одноимённые функции сведены 04.10 в одну).

Правило обхода одно на платформу: по умолчанию — только действующие предки
(согласование между компаниями, B8.1), ``include_archived=True`` — все
(наследование ролей, ``access.services.inheritance.ancestors_of``). В обоих
режимах — от родителя вверх, обход идёт через архив дальше, цикл не вешает.
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
def test_archived_intermediate_ancestor_is_included_on_request():
    """``include_archived=True`` (наследование ролей): архив обход не
    обрывает и из результата не выбрасывается — чьи роли действуют, решает
    вызывающий."""
    top = _co("t-anc-arch-top")
    mid = _co("t-anc-arch-mid", top, status=CompanyStatus.ARCHIVED)
    _co("t-anc-arch-low", mid)

    assert interface.ancestor_slugs("t-anc-arch-low", include_archived=True) == [
        "t-anc-arch-mid", "t-anc-arch-top",
    ]


@pytest.mark.django_db
def test_by_default_archived_is_skipped_but_walk_goes_on():
    """По умолчанию (согласование между компаниями, B8.1) архивной ступени
    в ответе нет, а действующий холдинг над ней — есть."""
    top = _co("t-anc-def-top")
    mid = _co("t-anc-def-mid", top, status=CompanyStatus.ARCHIVED)
    _co("t-anc-def-low", mid)

    assert interface.ancestor_slugs("t-anc-def-low") == ["t-anc-def-top"]


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
