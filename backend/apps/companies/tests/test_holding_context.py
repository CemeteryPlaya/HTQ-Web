"""Признак «идёт чтение сводки холдинга».

Нужен не ради удобства: читатели холдинга объявляют тот же db_table, что и
таблица компании (``hr_employee``), поэтому вне схемы ``holding`` они молча
прочитали бы ОДНУ компанию и выдали её цифры за групповые. Признак
позволяет менеджеру читателя потребовать контекст и упасть громко.
"""

from __future__ import annotations

import pytest

from htqweb.tenancy.db import holding_active, use_company, use_holding


@pytest.mark.django_db
def test_holding_is_not_active_by_default():
    assert holding_active() is False


@pytest.mark.django_db
def test_holding_is_active_inside_use_holding():
    with use_holding():
        assert holding_active() is True
    assert holding_active() is False


@pytest.mark.django_db
def test_holding_flag_falls_back_even_when_the_block_raises():
    with pytest.raises(RuntimeError):
        with use_holding():
            raise RuntimeError("прерванное чтение сводки")
    assert holding_active() is False


@pytest.mark.django_db
def test_company_context_does_not_pretend_to_be_holding():
    """use_company — не сводка: признак обязан остаться выключенным."""
    with use_company("acme"):
        assert holding_active() is False


@pytest.mark.django_db
def test_holding_inside_a_company_block_restores_the_flag():
    """Сводное чтение допустимо внутри открытой компании (докстринг
    use_holding это прямо оговаривает) — и выход обязан вернуть False."""
    with use_company("acme"):
        with use_holding():
            assert holding_active() is True
        assert holding_active() is False
