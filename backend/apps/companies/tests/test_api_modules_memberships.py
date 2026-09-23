"""Модули компании и членство через HTTP."""

import pytest
from django.test import Client

from apps.access.models import Role, RoleAssignment, ScopeKind
from apps.access.tests.helpers import grant as grant_permission
from apps.companies.models import Company, CompanyKind, CompanyMembership
from apps.companies.tests.api_helpers import (
    BASE, auth, headers, patch_json, post_json, superuser_token, token,
)
from apps.users.models import User, UserStatus


def _company_write_token(user_id: int, own_slug: str) -> str:
    """Токен с настоящим write на ``companies``, но только в ``own_slug``.
    Копия помощника из ``test_api_write.py`` — тесты соседних файлов не
    делят фикстуры/помощники в этой аппке (см. ``api_helpers.py``)."""
    role = Role.objects.create(code=f"companies-writer-{user_id}", title="Реестр — запись")
    grant_permission(role, "companies", "write")
    RoleAssignment.objects.create(company_slug=own_slug, user_id=user_id, role=role,
                                  scope_kind=ScopeKind.COMPANY, scope_id=None)
    return token(user_id=user_id, sub=str(user_id), company=own_slug)


@pytest.fixture
def client():
    return Client()


@pytest.fixture
def company(db):
    return Company.objects.create(slug="htq", name="HTQ", kind=CompanyKind.CONSTRUCTION)


@pytest.fixture
def other_company(db):
    """Компания звонящего в тестах межкомпанейского гейта — отдельная от
    ``company``, которую он пытается прочитать/изменить."""
    return Company.objects.create(slug="beta", name="Beta", kind=CompanyKind.CONSTRUCTION)


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
    # Блок I.2, R7: суперпользователь — ЗАВЕДОМО не ``user``. ``superuser_token()``
    # шьёт фиксированный ``user_id=9``, а id строки ``User`` выдаёт
    # последовательность Postgres, которую откат транзакции теста НЕ
    # отматывает: стоило соседним тестам создать ровно восемь пользователей
    # до этого, и ``user.id`` становился 9 — снятие членства превращалось в
    # «снять у себя» (409 ``self_revoke``) и тест падал от порядка прогона.
    # id от ``user.id`` не совпадает с ним ни при каком порядке.
    admin_id = user.id + 1
    admin = auth(token(user_id=admin_id, sub=str(admin_id), is_staff=True,
                       is_superuser=True, is_admin=True))

    res = post_json(client, f"{BASE}/companies/htq/memberships",
                    {"user_id": user.id, "is_default": True}, **admin)
    assert res.status_code == 201
    assert res.json()["username"] == "ivanov"
    assert res.json()["is_default"] is True

    # Повтор — 200, второй строки нет.
    res = post_json(client, f"{BASE}/companies/htq/memberships", {"user_id": user.id},
                    **admin)
    assert res.status_code == 200
    assert CompanyMembership.objects.filter(company=company).count() == 1

    res = client.get(f"{BASE}/companies/htq/memberships", **admin)
    assert [m["user_id"] for m in res.json()] == [user.id]

    res = client.delete(f"{BASE}/companies/htq/memberships/{user.id}", **admin)
    assert res.status_code == 204
    assert client.delete(f"{BASE}/companies/htq/memberships/{user.id}",
                         **admin).status_code == 404


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


# ── Финальное ревью: гейт слеп к slug из URL ─────────────────────────────

@pytest.mark.django_db
def test_membership_post_of_other_company_is_forbidden_for_company_scoped_writer(
    client, company, other_company, user,
):
    """Критическая находка: write на ``companies`` в СВОЕЙ компании
    (``beta``) не должен позволять выдать членство в чужой (``htq``) —
    членство несёт легитимный claim ``company`` и весь тенантный доступ."""
    tok = _company_write_token(201, other_company.slug)
    res = post_json(client, f"{BASE}/companies/{company.slug}/memberships",
                    {"user_id": user.id}, **headers(other_company.slug, tok))
    assert res.status_code == 403
    assert not CompanyMembership.objects.filter(company=company).exists()


@pytest.mark.django_db
def test_membership_get_of_other_company_is_forbidden_for_company_scoped_reader(
    client, company, other_company, user,
):
    """Важная находка: тот же разрыв на чтении — ростер участников (username/
    full_name/email) чужой компании не должен быть виден."""
    CompanyMembership.objects.create(company=company, user_id=user.id)
    tok = _company_write_token(202, other_company.slug)  # write покрывает read
    res = client.get(f"{BASE}/companies/{company.slug}/memberships",
                     **headers(other_company.slug, tok))
    assert res.status_code == 403


@pytest.mark.django_db
def test_superuser_still_manages_memberships_of_any_company(client, company, other_company, user):
    """Платформенный администратор проходит обе проверки независимо от того,
    какая компания указана в заголовке шлюза."""
    tok = superuser_token(company=other_company.slug)
    res = post_json(client, f"{BASE}/companies/{company.slug}/memberships",
                    {"user_id": user.id}, **headers(other_company.slug, tok))
    assert res.status_code == 201

    res = client.get(f"{BASE}/companies/{company.slug}/memberships",
                     **headers(other_company.slug, tok))
    assert res.status_code == 200
    assert [m["user_id"] for m in res.json()] == [user.id]
