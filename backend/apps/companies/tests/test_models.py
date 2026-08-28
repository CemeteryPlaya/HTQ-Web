import pytest
from django.core.exceptions import ValidationError
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


@pytest.mark.django_db
def test_slug_rejects_leading_digit():
    """Правка 3 итогового ревью: шлюз (default.conf) распознаёт компанию по
    поддомену через ``[a-z][a-z0-9-]*`` — первая метка обязана начинаться с
    буквы, чтобы IP-адрес не читался как компания. Slug вида "7hills" до
    этой правки заводился успешно и оставался молча недостижимым: nginx его
    поддомен никогда не матчил, заголовок X-HTQ-Company не ставился."""
    company = Company(slug="7hills", name="7 Hills", kind=CompanyKind.SERVICE)
    with pytest.raises(ValidationError):
        company.full_clean()


@pytest.mark.django_db
def test_slug_rejects_www():
    """"www" зарезервирован тем же образом, что и в default.conf
    (``(?!www\\.)``) — самый частый технический поддомен."""
    company = Company(slug="www", name="WWW", kind=CompanyKind.SERVICE)
    with pytest.raises(ValidationError):
        company.full_clean()


@pytest.mark.django_db
def test_slug_www_prefix_is_still_allowed():
    """Запрещён только полный "www", а не префикс — "www2"/"www-team"
    остаются валидными slug'ами, как и у nginx-регулярки."""
    company = Company(slug="www-team", name="WWW Team", kind=CompanyKind.SERVICE)
    company.full_clean()  # не должно поднимать ValidationError
