"""Задача 8 плана A: ``GET /me`` и та же карта прав в ответе профиля (§4.5)."""

import pytest
from django.test import Client

from apps.access.models import Level, Role, RoleAssignment, RoleModulePermission, ScopeKind
from apps.access.tests.helpers import BASE, auth, superuser_token, token


@pytest.fixture
def client():
    return Client()


@pytest.mark.django_db
def test_me_requires_authentication(client):
    assert client.get(f"{BASE}/me").status_code == 401


@pytest.mark.django_db
def test_me_without_company_is_not_an_error(client):
    """Переходный режим подпроекта 1: контекста компании нет — это не сбой."""
    resp = client.get(f"{BASE}/me", **auth(token()))
    assert resp.status_code == 200
    assert resp.json() == {"company": None, "permissions": {},
                           "subordinate_companies": []}


@pytest.mark.django_db
def test_me_returns_permissions_of_the_request_company(client, company_schema):
    slug = company_schema["slug"]
    role = Role.objects.create(code="r", title="Роль")
    RoleModulePermission.objects.create(role=role, module="hr", level=Level.WRITE)
    RoleAssignment.objects.create(company_slug=slug, user_id=7, role=role,
                                  scope_kind=ScopeKind.DEPARTMENT, scope_id=3)

    resp = client.get(f"{BASE}/me", HTTP_X_HTQ_COMPANY=slug,
                      **auth(token(company=slug)))
    assert resp.status_code == 200
    assert resp.json() == {
        "company": slug,
        "permissions": {"hr": {"level": "write",
                               "scope": {"kind": "department", "id": 3}}},
        "subordinate_companies": [],
    }


@pytest.mark.django_db
def test_modules_with_none_are_absent_from_me(client, company_schema):
    slug = company_schema["slug"]
    resp = client.get(f"{BASE}/me", HTTP_X_HTQ_COMPANY=slug,
                      **auth(token(company=slug)))
    assert resp.json()["permissions"] == {}


@pytest.mark.django_db
def test_superuser_sees_admin_on_every_module(client, company_schema):
    from apps.core.models import KNOWN_SERVICES

    slug = company_schema["slug"]
    resp = client.get(f"{BASE}/me", HTTP_X_HTQ_COMPANY=slug,
                      **auth(superuser_token(company=slug)))
    perms = resp.json()["permissions"]
    assert set(perms) == set(KNOWN_SERVICES)
    assert all(entry["level"] == "admin" for entry in perms.values())


# ── Та же карта в профиле ─────────────────────────────────────────────────


@pytest.mark.django_db
def test_profile_carries_the_same_permission_map(client, company_schema, django_user_model):
    """Чтобы фронт не делал второй запрос на каждой загрузке (спека A7)."""
    slug = company_schema["slug"]
    user = django_user_model.objects.create_user(username="u", email="u@htq.test",
                                                 password="x")
    role = Role.objects.create(code="r", title="Роль")
    RoleModulePermission.objects.create(role=role, module="tasks", level=Level.READ)
    RoleAssignment.objects.create(company_slug=slug, user_id=user.id, role=role,
                                  scope_kind=ScopeKind.COMPANY, scope_id=None)

    tok = token(user_id=user.id, sub=str(user.id), company=slug)
    me = client.get(f"{BASE}/me", HTTP_X_HTQ_COMPANY=slug, **auth(tok)).json()
    profile = client.get("/api/users/v1/profile/me", HTTP_X_HTQ_COMPANY=slug,
                         **auth(tok)).json()

    assert profile["permissions"] == me["permissions"]
    assert profile["company"] == me["company"]
    assert profile["subordinate_companies"] == me["subordinate_companies"]


@pytest.mark.django_db
def test_roles_for_still_returns_three_values(django_user_model):
    """Снимать их до задачи B4 значит уронить вход в систему (спека A7)."""
    from apps.users.services.profile_service import roles_for

    user = django_user_model.objects.create_user(username="plain", email="p@htq.test",
                                                 password="x")
    assert roles_for(user) == ["user"]
    user.is_staff = True
    assert roles_for(user) == ["staff"]
    user.is_superuser = True
    assert roles_for(user) == ["admin"]
