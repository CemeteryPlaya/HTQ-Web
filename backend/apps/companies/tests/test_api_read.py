"""Чтение реестра: /me, список, дерево, карточка. Коды и формы тел."""

import pytest
from django.test import Client

from apps.companies.models import Company, CompanyKind, CompanyMembership, CompanyStatus
from apps.companies.tests.api_helpers import (
    BASE, auth, headers, staff_token, superuser_token, token,
)


@pytest.fixture
def client():
    return Client()


@pytest.fixture
def group(db):
    holding = Company.objects.create(slug="hi-tech-group", name="Hi-Tech Group", kind=CompanyKind.HOLDING)
    htq = Company.objects.create(slug="hi-tech-qazaqstan", name="Hi-Tech Qazaqstan",
                                 kind=CompanyKind.CONSTRUCTION, country="KZ", parent=holding)
    keg = Company.objects.create(slug="keg", name="KEG", kind=CompanyKind.SERVICE, parent=holding,
                                 status=CompanyStatus.ARCHIVED)
    return {"holding": holding, "htq": htq, "keg": keg}


# ── /me ──────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_me_requires_auth(client):
    assert client.get(f"{BASE}/me").status_code == 401


@pytest.mark.django_db
def test_me_lists_active_memberships_and_marks_current(client, group):
    CompanyMembership.objects.create(company=group["htq"], user_id=7, is_default=True)
    CompanyMembership.objects.create(company=group["holding"], user_id=7)
    CompanyMembership.objects.create(company=group["keg"], user_id=7)  # архив — не показывать

    res = client.get(f"{BASE}/me", **headers("hi-tech-qazaqstan", token(company="hi-tech-qazaqstan")))
    assert res.status_code == 200
    assert res.json() == [
        {"slug": "hi-tech-qazaqstan", "subdomain": None, "name": "Hi-Tech Qazaqstan",
         "kind": "construction", "is_default": True, "is_current": True,
         "is_archived": False},
        {"slug": "hi-tech-group", "subdomain": None, "name": "Hi-Tech Group",
         "kind": "holding", "is_default": False, "is_current": False,
         "is_archived": False},
    ]


@pytest.mark.django_db
def test_me_without_company_header_marks_nothing_current(client, group):
    CompanyMembership.objects.create(company=group["htq"], user_id=7)
    res = client.get(f"{BASE}/me", **auth(token()))
    assert res.status_code == 200
    assert res.json()[0]["is_current"] is False


@pytest.mark.django_db
def test_me_adds_archived_companies_for_superuser(client, group):
    """Суперпользователю — все архивные компании реестра, без членства, после
    действующих; компанией по умолчанию архив не бывает."""
    CompanyMembership.objects.create(company=group["htq"], user_id=9, is_default=True)

    res = client.get(f"{BASE}/me", **headers(
        "hi-tech-qazaqstan", superuser_token(company="hi-tech-qazaqstan")))

    assert res.status_code == 200
    assert [(c["slug"], c["is_archived"], c["is_default"]) for c in res.json()] == [
        ("hi-tech-qazaqstan", False, True),
        ("keg", True, False),
    ]


@pytest.mark.django_db
def test_me_on_archived_subdomain_marks_it_current(client, group):
    res = client.get(f"{BASE}/me", **headers("keg", superuser_token(company="keg")))

    assert res.status_code == 200
    assert res.json() == [
        {"slug": "keg", "subdomain": None, "name": "KEG", "kind": "service",
         "is_default": False, "is_current": True, "is_archived": True},
    ]


# ── Реестр ───────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_registry_is_closed_to_users_without_the_module(client, group):
    """Без контекста компании уровень у обычного пользователя — none: 403."""
    assert client.get(f"{BASE}/companies", **auth(token())).status_code == 403
    assert client.get(f"{BASE}/companies", **auth(staff_token())).status_code == 403


@pytest.mark.django_db
def test_superuser_lists_all_by_default_and_filters_by_status(client, group):
    res = client.get(f"{BASE}/companies", **auth(superuser_token()))
    assert res.status_code == 200
    assert [c["slug"] for c in res.json()] == ["hi-tech-group", "hi-tech-qazaqstan", "keg"]
    htq = next(c for c in res.json() if c["slug"] == "hi-tech-qazaqstan")
    assert htq == {"id": group["htq"].id, "slug": "hi-tech-qazaqstan", "subdomain": None,
                   "name": "Hi-Tech Qazaqstan",
                   "kind": "construction", "status": "active", "country": "KZ",
                   "parent_slug": "hi-tech-group", "successor_slug": None, "archived_at": None,
                   # Задача 7 блока C: включено по умолчанию (решение заказчика 4).
                   "show_external_holders": True}

    res = client.get(f"{BASE}/companies?status=archived", **auth(superuser_token()))
    assert [c["slug"] for c in res.json()] == ["keg"]
    assert client.get(f"{BASE}/companies?status=bogus", **auth(superuser_token())).status_code == 422


@pytest.mark.django_db
def test_tree_nests_active_children_under_roots(client, group):
    res = client.get(f"{BASE}/companies/tree", **auth(superuser_token()))
    assert res.status_code == 200
    assert res.json() == [{
        "slug": "hi-tech-group", "name": "Hi-Tech Group", "kind": "holding",
        "status": "active", "country": "",
        "children": [{
            "slug": "hi-tech-qazaqstan", "name": "Hi-Tech Qazaqstan", "kind": "construction",
            "status": "active", "country": "KZ", "children": [],
        }],
    }]


@pytest.mark.django_db
def test_item_and_404(client, group):
    res = client.get(f"{BASE}/companies/keg", **auth(superuser_token()))
    assert res.status_code == 200
    assert res.json()["status"] == "archived"
    assert res.json()["archived_at"] is None  # архивирована фикстурой напрямую, без lifecycle
    assert client.get(f"{BASE}/companies/nope", **auth(superuser_token())).status_code == 404
