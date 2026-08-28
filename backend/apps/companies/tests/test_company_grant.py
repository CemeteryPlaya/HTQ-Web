"""``manage.py company_grant`` — выдача CompanyMembership вручную.

Не трогает схему Postgres (в отличие от ``company_create``/
``tenancy_bootstrap``) — обычный ``django_db`` без ``transaction=True``
достаточен, откат делает сам pytest-django.
"""

import pytest
from django.core.management import CommandError, call_command

from apps.companies.models import Company, CompanyKind, CompanyMembership
from apps.users.models import User, UserStatus


@pytest.fixture
def company(db):
    return Company.objects.create(slug="htq-kz", name="Hi-Tech Qazaqstan",
                                  kind=CompanyKind.REGIONAL)


@pytest.fixture
def active_user(db):
    return User.objects.create(username="ivanov", email="ivanov@example.test",
                               password="x", status=UserStatus.ACTIVE)


@pytest.fixture
def inactive_user(db):
    return User.objects.create(username="suspended", email="suspended@example.test",
                               password="x", status=UserStatus.SUSPENDED)


@pytest.mark.django_db
def test_unknown_company_is_an_error():
    with pytest.raises(CommandError):
        call_command("company_grant", "--company", "нет-такой", "--all-users")


@pytest.mark.django_db
def test_user_and_all_users_together_is_an_error(company):
    with pytest.raises(CommandError):
        call_command("company_grant", "--company", company.slug,
                     "--user", "1", "--all-users")


@pytest.mark.django_db
def test_neither_user_nor_all_users_is_an_error(company):
    with pytest.raises(CommandError):
        call_command("company_grant", "--company", company.slug)


@pytest.mark.django_db
def test_grant_by_id(company, active_user):
    call_command("company_grant", company_slug=company.slug, user=str(active_user.id))
    membership = CompanyMembership.objects.get(company=company, user_id=active_user.id)
    assert membership.is_default is False


@pytest.mark.django_db
def test_grant_by_username(company, active_user):
    call_command("company_grant", company_slug=company.slug, user=active_user.username)
    assert CompanyMembership.objects.filter(
        company=company, user_id=active_user.id,
    ).exists()


@pytest.mark.django_db
def test_grant_by_username_case_insensitive(company, active_user):
    call_command("company_grant", company_slug=company.slug,
                 user=active_user.username.upper())
    assert CompanyMembership.objects.filter(
        company=company, user_id=active_user.id,
    ).exists()


@pytest.mark.django_db
def test_unknown_user_is_an_error(company):
    with pytest.raises(CommandError):
        call_command("company_grant", company_slug=company.slug, user="99999999")
    with pytest.raises(CommandError):
        call_command("company_grant", company_slug=company.slug, user="нет-такого-юзера")


@pytest.mark.django_db
def test_grant_all_users_includes_only_active(company, active_user, inactive_user):
    call_command("company_grant", company_slug=company.slug, all_users=True)

    assert CompanyMembership.objects.filter(
        company=company, user_id=active_user.id,
    ).exists()
    assert not CompanyMembership.objects.filter(
        company=company, user_id=inactive_user.id,
    ).exists()


@pytest.mark.django_db
def test_repeated_run_does_not_duplicate(company, active_user):
    """Идемпотентность — повторный запуск не плодит вторую строку членства
    (упёрлась бы в uniq_membership) и не падает."""
    call_command("company_grant", company_slug=company.slug, user=str(active_user.id))
    call_command("company_grant", company_slug=company.slug, user=str(active_user.id))

    assert CompanyMembership.objects.filter(
        company=company, user_id=active_user.id,
    ).count() == 1
