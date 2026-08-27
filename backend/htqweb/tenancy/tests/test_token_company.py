import pytest
from django.test import Client

from apps.companies.models import Company, CompanyKind, CompanyMembership
from apps.users.models import User, UserStatus
from htqweb.authn.jwt import decode_token, issue_token_pair


@pytest.fixture
def user(db):
    return User.objects.create_user(
        username="ivan", email="ivan@htq.kz", password="pw",
        status=UserStatus.ACTIVE,
    )


@pytest.fixture
def companies(db):
    kz = Company.objects.create(slug="htq-kz", name="KZ", kind=CompanyKind.REGIONAL)
    uz = Company.objects.create(slug="htq-uz", name="UZ", kind=CompanyKind.REGIONAL)
    return kz, uz


@pytest.mark.django_db
def test_access_token_carries_default_company(user, companies):
    kz, _ = companies
    CompanyMembership.objects.create(user_id=user.id, company=kz, is_default=True)
    pair = issue_token_pair(user)
    assert decode_token(pair["access"]).company == "htq-kz"


@pytest.mark.django_db
def test_token_without_membership_has_no_company(user, companies):
    pair = issue_token_pair(user)
    assert decode_token(pair["access"]).company is None


@pytest.mark.django_db
def test_token_of_one_company_is_rejected_on_another(user, companies):
    """Вторая линия обороны поддоменной схемы.

    Без неё токен, полученный на kz.htqweb.kz, работал бы и на uz.htqweb.kz —
    поддомен подменяется тривиально, подпись токена нет.
    """
    kz, _ = companies
    CompanyMembership.objects.create(user_id=user.id, company=kz, is_default=True)
    access = issue_token_pair(user)["access"]

    ok = Client().get("/api/users/v1/profile/me",
                      HTTP_AUTHORIZATION=f"Bearer {access}",
                      HTTP_X_HTQ_COMPANY="htq-kz")
    assert ok.status_code == 200

    denied = Client().get("/api/users/v1/profile/me",
                          HTTP_AUTHORIZATION=f"Bearer {access}",
                          HTTP_X_HTQ_COMPANY="htq-uz")
    assert denied.status_code == 403
    assert denied.json() == {"detail": "Forbidden"}
