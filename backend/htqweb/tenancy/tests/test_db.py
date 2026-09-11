import pytest
from django.db import connection

from htqweb.tenancy.context import current_company_or_none
from htqweb.tenancy.db import apply_search_path, use_company, use_holding


def _search_path() -> str:
    with connection.cursor() as cur:
        cur.execute("SHOW search_path")
        return cur.fetchone()[0]


@pytest.mark.django_db
def test_apply_puts_company_schema_first():
    apply_search_path("htq-kz")
    assert _search_path().startswith("co_htq_kz")
    apply_search_path(None)


@pytest.mark.django_db
def test_public_can_be_excluded_for_migrations():
    """Во время миграции public исключается намеренно.

    Иначе Django находит public.django_migrations и все компании начинают
    считать себя мигрированными вместе.
    """
    apply_search_path("htq-kz", include_public=False)
    assert "public" not in _search_path()
    apply_search_path(None)


@pytest.mark.django_db
def test_use_company_restores_previous_state():
    with use_company("htq-kz"):
        assert current_company_or_none() == "htq-kz"
        assert _search_path().startswith("co_htq_kz")
    assert current_company_or_none() is None
    assert _search_path().startswith("public")


@pytest.mark.django_db
def test_use_company_restores_on_exception():
    with pytest.raises(ValueError):
        with use_company("htq-kz"):
            raise ValueError("боом")
    assert current_company_or_none() is None
    assert _search_path().startswith("public")


@pytest.mark.django_db
def test_use_holding_selects_holding_schema():
    with use_holding():
        assert _search_path().startswith("holding")
    assert _search_path().startswith("public")


@pytest.mark.django_db
def test_use_holding_restores_on_exception():
    with pytest.raises(ValueError):
        with use_holding():
            raise ValueError("боом")
    assert _search_path().startswith("public")


@pytest.mark.django_db
def test_use_holding_inside_a_company_restores_that_company():
    """Именно этот сценарий и пропустили: сводное чтение холдинга вполне может
    выполняться внутри запроса, где компания уже установлена, и после выхода
    соединение обязано вернуться в её схему, а не в public."""
    with use_company("htq-kz"):
        with use_holding():
            assert _search_path().startswith("holding")
        assert _search_path().startswith("co_htq_kz")
    assert _search_path().startswith("public")
