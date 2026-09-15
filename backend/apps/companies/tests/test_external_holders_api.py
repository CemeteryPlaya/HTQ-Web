"""``GET companies/<slug>/external-holders`` — задача 7 блока C.

Гейт (``deny_unless_own_company``) и настройка (``show_external_holders``)
проверяются здесь через HTTP, на подменённом ``apps.access.interface.
external_holders`` — сама сборка списка (обход предков, обслуживающие
должности, уровни модулей) настоящими схемами компаний проверена в
``apps/access/tests/test_external_holders.py``. Разделение то же, что у
блока A: HTTP-слой companies не знает и не должен знать, КАК access считает
список, только КОГДА его можно показать.
"""

from __future__ import annotations

import pytest
from django.test import Client

from apps.access.models import Role, RoleAssignment, ScopeKind
from apps.access.tests.helpers import grant as grant_permission
from apps.companies.models import Company, CompanyKind
from apps.companies.tests.api_helpers import BASE, auth, headers, superuser_token, token

_CANNED_ROW = {
    "full_name": "Иванов Иван",
    "home_company": "Hi-Tech Group",
    "position": "Главный бухгалтер",
    "modules": [{"module": "hr", "level": "read"}],
}


def _company_reader_token(user_id: int, own_slug: str) -> str:
    """Токен с настоящим read на ``companies``, но только в ``own_slug`` —
    копия приёма ``_company_write_token`` из ``test_api_write.py``."""
    role = Role.objects.create(code=f"companies-reader-{user_id}", title="Реестр — чтение")
    grant_permission(role, "companies", "read")
    RoleAssignment.objects.create(company_slug=own_slug, user_id=user_id, role=role,
                                  scope_kind=ScopeKind.COMPANY, scope_id=None)
    return token(user_id=user_id, sub=str(user_id), company=own_slug)


@pytest.fixture
def client():
    return Client()


@pytest.fixture
def company(db):
    return Company.objects.create(slug="htq", name="HTQ", kind=CompanyKind.CONSTRUCTION)


@pytest.mark.django_db
def test_external_holders_is_closed_to_a_reader_of_another_company(client, company):
    other = Company.objects.create(slug="beta", name="Beta", kind=CompanyKind.CONSTRUCTION)
    tok = _company_reader_token(301, other.slug)
    res = client.get(f"{BASE}/companies/{company.slug}/external-holders",
                     **headers(other.slug, tok))
    assert res.status_code == 403


@pytest.mark.django_db
def test_external_holders_hidden_setting_returns_403_with_explanatory_body(client, company):
    """Выключенная настройка — 403 с внятным телом, а НЕ пустой список:
    пустой список сказал бы «внешних держателей нет», и это была бы ложь."""
    company.show_external_holders = False
    company.save(update_fields=["show_external_holders"])

    res = client.get(f"{BASE}/companies/{company.slug}/external-holders",
                     **auth(superuser_token()))
    assert res.status_code == 403
    body = res.json()
    assert body.get("detail")
    assert body["detail"] != []


@pytest.mark.django_db
def test_external_holders_returns_access_module_list_when_setting_on(client, company, monkeypatch):
    calls = []

    def _fake(slug):
        calls.append(slug)
        return [_CANNED_ROW]

    monkeypatch.setattr("apps.access.interface.external_holders", _fake)

    res = client.get(f"{BASE}/companies/{company.slug}/external-holders",
                     **auth(superuser_token()))
    assert res.status_code == 200
    assert res.json() == [_CANNED_ROW]
    assert calls == [company.slug]


@pytest.mark.django_db
def test_external_holders_own_company_reader_is_allowed(client, company, monkeypatch):
    monkeypatch.setattr("apps.access.interface.external_holders", lambda slug: [])
    tok = _company_reader_token(302, company.slug)
    res = client.get(f"{BASE}/companies/{company.slug}/external-holders",
                     **headers(company.slug, tok))
    assert res.status_code == 200
    assert res.json() == []


@pytest.mark.django_db
def test_external_holders_unknown_company_is_404(client):
    res = client.get(f"{BASE}/companies/does-not-exist/external-holders",
                     **auth(superuser_token()))
    assert res.status_code == 404
