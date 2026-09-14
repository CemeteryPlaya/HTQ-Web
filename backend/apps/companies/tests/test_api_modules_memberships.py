"""Модули компании и членство через HTTP."""

import pytest
from django.test import Client

from apps.companies.models import Company, CompanyKind, CompanyMembership
from apps.companies.tests.api_helpers import (
    BASE, auth, patch_json, post_json, superuser_token, token,
)
from apps.users.models import User, UserStatus


@pytest.fixture
def client():
    return Client()


@pytest.fixture
def company(db):
    return Company.objects.create(slug="htq", name="HTQ", kind=CompanyKind.CONSTRUCTION)


@pytest.fixture
def user(db):
    return User.objects.create(username="ivanov", email="ivanov@example.test",
                               password="x", status=UserStatus.ACTIVE)


@pytest.mark.django_db
def test_modules_list_and_patch(client, company):
    res = client.get(f"{BASE}/companies/htq/modules", **auth(superuser_token()))
    assert res.status_code == 200
    tasks = next(m for m in res.json() if m["app_label"] == "tasks")
    assert tasks == {"app_label": "tasks", "enabled": True, "message": "", "is_core": False}

    res = patch_json(client, f"{BASE}/companies/htq/modules/tasks",
                     {"enabled": False, "message": "Закрыто на инвентаризацию"},
                     **auth(superuser_token()))
    assert res.status_code == 200
    assert res.json()["enabled"] is False
    assert res.json()["message"] == "Закрыто на инвентаризацию"


@pytest.mark.django_db
def test_modules_core_is_409_and_unknown_is_422(client, company):
    res = patch_json(client, f"{BASE}/companies/htq/modules/hr", {"enabled": False},
                     **auth(superuser_token()))
    assert res.status_code == 409
    res = patch_json(client, f"{BASE}/companies/htq/modules/warehouse", {"enabled": False},
                     **auth(superuser_token()))
    assert res.status_code == 422


@pytest.mark.django_db
def test_memberships_grant_list_revoke(client, company, user):
    res = post_json(client, f"{BASE}/companies/htq/memberships",
                    {"user_id": user.id, "is_default": True}, **auth(superuser_token()))
    assert res.status_code == 201
    assert res.json()["username"] == "ivanov"
    assert res.json()["is_default"] is True

    # Повтор — 200, второй строки нет.
    res = post_json(client, f"{BASE}/companies/htq/memberships", {"user_id": user.id},
                    **auth(superuser_token()))
    assert res.status_code == 200
    assert CompanyMembership.objects.filter(company=company).count() == 1

    res = client.get(f"{BASE}/companies/htq/memberships", **auth(superuser_token()))
    assert [m["user_id"] for m in res.json()] == [user.id]

    res = client.delete(f"{BASE}/companies/htq/memberships/{user.id}", **auth(superuser_token()))
    assert res.status_code == 204
    assert client.delete(f"{BASE}/companies/htq/memberships/{user.id}",
                         **auth(superuser_token())).status_code == 404


@pytest.mark.django_db
def test_membership_grant_rejects_unknown_user(client, company):
    res = post_json(client, f"{BASE}/companies/htq/memberships", {"user_id": 424242},
                    **auth(superuser_token()))
    assert res.status_code == 422


@pytest.mark.django_db
def test_cannot_revoke_own_membership(client, company):
    CompanyMembership.objects.create(company=company, user_id=9)  # 9 = superuser_token
    res = client.delete(f"{BASE}/companies/htq/memberships/9", **auth(superuser_token()))
    assert res.status_code == 409
    assert res.json()["code"] == "self_revoke"


@pytest.mark.django_db
def test_membership_delete_is_platform_only(client, company, user):
    CompanyMembership.objects.create(company=company, user_id=user.id)
    assert client.delete(f"{BASE}/companies/htq/memberships/{user.id}",
                         **auth(token())).status_code == 403
