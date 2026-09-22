"""Псевдоним компании в адресе — Company.subdomain (блок I.2, S1).

Слаг остаётся именем схемы (``co_<slug>``) и значением в ролях и токенах;
псевдоним — только адрес. Поэтому он отдельным полем, а не переименованием.
"""
from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError

from apps.companies.models import Company, CompanyKind


@pytest.mark.django_db
def test_subdomain_is_optional():
    company = Company(slug="acme", name="Acme", kind=CompanyKind.IT)
    company.full_clean()
    company.save()
    assert company.subdomain is None


@pytest.mark.django_db
def test_two_companies_may_both_have_no_subdomain():
    Company.objects.create(slug="acme", name="Acme", kind=CompanyKind.IT)
    Company.objects.create(slug="beta", name="Beta", kind=CompanyKind.IT)
    assert Company.objects.filter(subdomain__isnull=True).count() == 2


@pytest.mark.django_db
def test_reserved_label_is_rejected():
    company = Company(slug="acme", name="Acme", kind=CompanyKind.IT, subdomain="api")
    with pytest.raises(ValidationError) as exc:
        company.full_clean()
    assert "subdomain" in exc.value.message_dict


@pytest.mark.django_db
def test_subdomain_may_not_collide_with_another_companys_slug():
    Company.objects.create(slug="acme", name="Acme", kind=CompanyKind.IT)
    other = Company(slug="beta", name="Beta", kind=CompanyKind.IT, subdomain="acme")
    with pytest.raises(ValidationError) as exc:
        other.full_clean()
    assert "subdomain" in exc.value.message_dict


@pytest.mark.django_db
def test_slug_may_not_collide_with_another_companys_subdomain():
    Company.objects.create(slug="acme", name="Acme", kind=CompanyKind.IT,
                           subdomain="htq")
    other = Company(slug="htq", name="HTQ", kind=CompanyKind.IT)
    with pytest.raises(ValidationError) as exc:
        other.full_clean()
    assert "slug" in exc.value.message_dict


@pytest.mark.django_db
def test_own_slug_as_own_subdomain_is_allowed():
    """Свой же слаг псевдонимом — не столкновение: хост тот же самый."""
    company = Company(slug="acme", name="Acme", kind=CompanyKind.IT, subdomain="acme")
    company.full_clean()
    company.save()
    assert company.subdomain == "acme"


@pytest.mark.django_db
def test_provision_company_accepts_subdomain():
    from apps.companies.services import lifecycle

    company = lifecycle.provision_company(
        slug="acme-corp", name="Acme", kind=CompanyKind.IT, subdomain="acme",
    )
    assert company.subdomain == "acme"


@pytest.mark.django_db
def test_update_company_sets_and_clears_subdomain():
    from apps.companies.services import lifecycle

    lifecycle.provision_company(slug="acme-corp", name="Acme", kind=CompanyKind.IT)
    assert lifecycle.update_company("acme-corp", subdomain="acme").subdomain == "acme"
    # Пустая строка — «убрать псевдоним», компания возвращается на слаг.
    assert lifecycle.update_company("acme-corp", subdomain="").subdomain is None
    # Ключ не передан — «не трогать».
    assert lifecycle.update_company("acme-corp", name="Acme 2").subdomain is None


@pytest.mark.django_db
def test_registry_row_carries_subdomain():
    from apps.companies import interface

    Company.objects.create(slug="acme", name="Acme", kind=CompanyKind.IT,
                           subdomain="ac")
    assert interface.get_company("acme")["subdomain"] == "ac"
