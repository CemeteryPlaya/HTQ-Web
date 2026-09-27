"""Значения справочников на дату (BR-031, BR-040, CALC-011, CALC-012)."""

from datetime import date
from decimal import Decimal

import pytest

from apps.refdata import interface
from apps.refdata.models import Article, ArticleGroup, ExchangeRate


@pytest.mark.django_db
def test_vat_on_a_date_uses_the_period_boundaries():
    assert interface.vat_rate("KZ", date(2025, 12, 31)) == Decimal("12.00")
    assert interface.vat_rate("KZ", date(2026, 1, 1)) == Decimal("16.00")
    assert interface.vat_rate("XX", date(2026, 1, 1)) is None


@pytest.mark.django_db
def test_mrp_and_threshold():
    assert interface.mrp(date(2026, 9, 1)) == Decimal("4325.00")
    assert interface.contract_threshold(date(2026, 9, 1)) == Decimal("4325000.00")
    assert interface.mrp(date(2025, 6, 1)) == Decimal("3932.00")
    with pytest.raises(interface.RefdataMissing):
        interface.mrp(date(2019, 1, 1))


@pytest.mark.django_db
def test_exchange_rate():
    assert interface.exchange_rate("KZT", date(2026, 9, 1)) == Decimal("1")
    ExchangeRate.objects.create(currency_code="USD", on_date=date(2026, 9, 1),
                                rate=Decimal("470.120000"), source="nbrk")
    assert interface.exchange_rate("USD", date(2026, 9, 1)) == Decimal("470.120000")
    assert interface.exchange_rate("USD", date(2026, 9, 2)) is None


@pytest.mark.django_db
def test_archived_article_is_still_described():
    group = ArticleGroup.objects.get(code="supply")
    article = Article.objects.create(code="111", name="Металлопрокат", group=group,
                                     is_active=False)
    brief = interface.article_brief([str(article.id)])[str(article.id)]
    assert brief == {"id": str(article.id), "code": "111", "name": "Металлопрокат",
                     "group_id": str(group.id), "node_key": "bpp.articles.supply",
                     "is_active": False}
    assert {g["code"] for g in interface.article_groups()} == {"supply", "pm"}
