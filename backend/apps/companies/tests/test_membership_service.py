"""Членство: список с данными учётки и отзыв."""

import pytest

from apps.companies.models import Company, CompanyKind, CompanyMembership
from apps.companies.services import membership_service
from apps.users.models import User, UserStatus


@pytest.fixture
def company(db):
    return Company.objects.create(slug="htq", name="HTQ", kind=CompanyKind.CONSTRUCTION)


@pytest.fixture
def user(db):
    return User.objects.create(username="ivanov", email="ivanov@example.test",
                               password="x", first_name="Иван", last_name="Иванов",
                               status=UserStatus.ACTIVE)


@pytest.mark.django_db
def test_list_joins_user_brief(company, user):
    membership_service.grant_membership(company, user.id, is_default=True)
    rows = membership_service.list_memberships(company)
    assert rows == [{
        "user_id": user.id, "username": "ivanov", "full_name": "Иван Иванов",
        "email": "ivanov@example.test", "is_active": True, "is_default": True,
    }]


@pytest.mark.django_db
def test_list_keeps_membership_of_a_deleted_account(company):
    """Учётки нет, строка есть: показать, а не спрятать — иначе её не отозвать."""
    CompanyMembership.objects.create(company=company, user_id=999_999)
    rows = membership_service.list_memberships(company)
    assert rows[0]["user_id"] == 999_999
    assert rows[0]["username"] == ""
    assert rows[0]["is_active"] is False


@pytest.mark.django_db
def test_revoke_is_idempotent(company, user):
    membership_service.grant_membership(company, user.id)
    assert membership_service.revoke_membership(company, user.id) is True
    assert membership_service.revoke_membership(company, user.id) is False
    assert not CompanyMembership.objects.filter(company=company).exists()
