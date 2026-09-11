import pytest

from htqweb.tenancy.context import (
    NoCompanyContext, current_company, current_company_or_none,
    reset_company, schema_for, set_company,
)


def test_schema_name_replaces_dashes():
    """Дефис допустим в DNS-метке, но не в идентификаторе Postgres."""
    assert schema_for("htq-kz") == "co_htq_kz"
    assert schema_for("kup") == "co_kup"


def test_no_context_raises():
    """Пустой контекст — ошибка, а не молчаливый public.

    Это тот же принцип, что и FALLBACK_MODE=strict: подмена, которой
    никто не закладывал, обязана быть падающим тестом.
    """
    assert current_company_or_none() is None
    with pytest.raises(NoCompanyContext):
        current_company()


def test_set_and_reset_are_symmetric():
    token = set_company("htq-kz")
    assert current_company() == "htq-kz"
    reset_company(token)
    assert current_company_or_none() is None


def test_nesting_restores_outer_value():
    outer = set_company("htq-kz")
    inner = set_company("htq-uz")
    assert current_company() == "htq-uz"
    reset_company(inner)
    assert current_company() == "htq-kz"
    reset_company(outer)
