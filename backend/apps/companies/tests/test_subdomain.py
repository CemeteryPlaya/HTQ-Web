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


# ── Метка хоста → компания (задача 4 блока I.2) ─────────────────────────────


@pytest.mark.django_db
def test_host_label_resolves_by_subdomain_first():
    from apps.companies import interface

    Company.objects.create(slug="hi-tech-qazaqstan", name="HTQ",
                           kind=CompanyKind.CONSTRUCTION, subdomain="htq")
    assert interface.resolve_host_label("htq")["slug"] == "hi-tech-qazaqstan"


@pytest.mark.django_db
def test_company_with_alias_is_not_reachable_by_slug():
    """Один канонический хост на компанию: иначе два origin'а и два localStorage."""
    from apps.companies import interface

    Company.objects.create(slug="hi-tech-qazaqstan", name="HTQ",
                           kind=CompanyKind.CONSTRUCTION, subdomain="htq")
    assert interface.resolve_host_label("hi-tech-qazaqstan") is None


@pytest.mark.django_db
def test_company_without_alias_is_reachable_by_slug():
    from apps.companies import interface

    Company.objects.create(slug="acme", name="Acme", kind=CompanyKind.IT)
    assert interface.resolve_host_label("acme")["slug"] == "acme"


@pytest.mark.django_db
def test_unknown_label_resolves_to_none():
    from apps.companies import interface

    assert interface.resolve_host_label("nope") is None


@pytest.mark.django_db
def test_public_url_uses_alias(settings):
    from apps.companies import interface

    settings.PUBLIC_BASE_URL = "https://htq.group"
    Company.objects.create(slug="hi-tech-qazaqstan", name="HTQ",
                           kind=CompanyKind.CONSTRUCTION, subdomain="htq")
    assert interface.public_url("hi-tech-qazaqstan") == "https://htq.htq.group"


@pytest.mark.django_db
def test_public_url_falls_back_to_slug(settings):
    from apps.companies import interface

    settings.PUBLIC_BASE_URL = "https://htq.group"
    Company.objects.create(slug="acme", name="Acme", kind=CompanyKind.IT)
    assert interface.public_url("acme") == "https://acme.htq.group"


@pytest.mark.django_db
def test_public_url_is_none_without_public_base_url(settings):
    from apps.companies import interface

    settings.PUBLIC_BASE_URL = ""
    Company.objects.create(slug="acme", name="Acme", kind=CompanyKind.IT)
    assert interface.public_url("acme") is None


@pytest.mark.django_db
@pytest.mark.parametrize("base", ["htq.group", "//htq.group", "https://"])
def test_public_url_is_none_without_scheme_or_host(settings, base):
    """``PUBLIC_BASE_URL`` без схемы или без хоста даёт ``None``, а не
    ``"://acme."`` — вызывающий откатывается на прежний источник (блок I.2, B2)."""
    from apps.companies import interface

    settings.PUBLIC_BASE_URL = base
    Company.objects.create(slug="acme", name="Acme", kind=CompanyKind.IT)
    assert interface.public_url("acme") is None


@pytest.mark.django_db
def test_host_label_prefers_alias_over_another_companys_slug():
    """Коллизия «псевдоним одной компании = слаг другой» (блок I.2, B4).

    ``Company.clean()`` её запрещает, но миграция ``0006`` ставит псевдонимы
    через ``.update()`` мимо валидации — поэтому порядок резолва должен
    отвечать и за такое состояние: псевдоним побеждает, и метку ``htq``
    получает компания B, а не A со слагом ``htq``.
    """
    from apps.companies import interface

    Company.objects.create(slug="htq", name="A", kind=CompanyKind.IT)
    b = Company.objects.create(slug="hi-tech-qazaqstan", name="B",
                               kind=CompanyKind.CONSTRUCTION)
    Company.objects.filter(pk=b.pk).update(subdomain="htq")

    assert interface.resolve_host_label("htq")["slug"] == "hi-tech-qazaqstan"
