import pytest
from django.db import IntegrityError

from apps.companies.models import (
    Company, CompanyKind, CompanyServiceLink, CompanyStatus,
)


@pytest.mark.django_db
def test_holding_has_no_parent():
    holding = Company.objects.create(
        slug="htq", name="Hi-Tech Group LTD", kind=CompanyKind.HOLDING,
    )
    assert holding.parent is None
    assert holding.status == CompanyStatus.ACTIVE


@pytest.mark.django_db
def test_regional_company_points_at_holding():
    holding = Company.objects.create(
        slug="htq", name="Hi-Tech Group LTD", kind=CompanyKind.HOLDING,
    )
    kz = Company.objects.create(
        slug="htq-kz", name="Hi-Tech Qazaqstan",
        kind=CompanyKind.REGIONAL, parent=holding, country="KZ",
    )
    assert list(holding.children.all()) == [kz]


@pytest.mark.django_db
def test_slug_is_unique():
    Company.objects.create(slug="htq-kz", name="A", kind=CompanyKind.REGIONAL)
    with pytest.raises(IntegrityError):
        Company.objects.create(slug="htq-kz", name="B", kind=CompanyKind.REGIONAL)


@pytest.mark.django_db
def test_service_link_is_many_to_many_across_regions():
    """Одна сервисная компания обслуживает несколько региональных.

    Это перекрёстные стрелки ТМЗ с исходной схемы: граф услуг не совпадает
    с деревом владения, поэтому он и вынесен в отдельную модель.
    """
    kup = Company.objects.create(slug="kup", name="КУП", kind=CompanyKind.SERVICE)
    kz = Company.objects.create(slug="htq-kz", name="KZ", kind=CompanyKind.REGIONAL)
    kg = Company.objects.create(slug="kurly-kg", name="KG", kind=CompanyKind.REGIONAL)

    CompanyServiceLink.objects.create(provider=kup, consumer=kz)
    CompanyServiceLink.objects.create(provider=kup, consumer=kg)

    assert kup.provided_services.count() == 2
