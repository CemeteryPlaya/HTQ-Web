"""Правка, архив и восстановление через HTTP: гейты и коды."""

import pytest
from django.db import connection
from django.test import Client

from apps.companies.models import Company, CompanyKind, CompanyStatus
from apps.companies.tests.api_helpers import (
    BASE, auth, patch_json, staff_token, superuser_token, token,
)


def _drop_holding_schema() -> None:
    with connection.cursor() as cur:
        cur.execute("DROP SCHEMA IF EXISTS holding CASCADE")


@pytest.fixture
def two_companies(two_company_schemas):
    """``two_company_schemas`` уже заводит строки реестра для обеих схем —
    здесь только уборка holding на выходе (сам fixture из conftest.py
    чистит только данные внутри схем компаний, про схему holding не знает).
    Копия ``two_companies`` из ``test_company_archive.py`` — тесты соседних
    файлов не делят фикстуры, а тест ниже пересобирает сводки холдинга так
    же, как команды ``company_archive``/``company_restore``."""
    try:
        yield two_company_schemas
    finally:
        _drop_holding_schema()


@pytest.fixture
def client():
    return Client()


@pytest.fixture
def pair(db):
    holding = Company.objects.create(slug="hi-tech-group", name="Group", kind=CompanyKind.HOLDING)
    htq = Company.objects.create(slug="hi-tech-qazaqstan", name="HTQ", kind=CompanyKind.REGIONAL)
    return holding, htq


@pytest.mark.django_db
def test_patch_sets_kind_and_parent_of_the_transition_company(client, pair):
    """Сценарий roadmap §3 п.6: единственная компания получает kind и родителя правкой."""
    res = patch_json(client, f"{BASE}/companies/hi-tech-qazaqstan",
                     {"kind": "construction", "parent_slug": "hi-tech-group", "country": "KZ"},
                     **auth(superuser_token()))
    assert res.status_code == 200
    assert res.json()["kind"] == "construction"
    assert res.json()["parent_slug"] == "hi-tech-group"
    assert res.json()["country"] == "KZ"


@pytest.mark.django_db
def test_patch_rejects_cycle_unknown_parent_and_bad_kind(client, pair):
    holding, htq = pair
    htq.parent = holding
    htq.save()
    res = patch_json(client, f"{BASE}/companies/hi-tech-group", {"parent_slug": "hi-tech-qazaqstan"},
                     **auth(superuser_token()))
    assert res.status_code == 422
    assert res.json()["code"] == "parent_cycle"

    res = patch_json(client, f"{BASE}/companies/hi-tech-group", {"parent_slug": "nope"},
                     **auth(superuser_token()))
    assert res.status_code == 422
    assert res.json()["code"] == "parent_not_found"

    res = patch_json(client, f"{BASE}/companies/hi-tech-group", {"kind": "branch"},
                     **auth(superuser_token()))
    assert res.status_code == 422  # схема отбивает до сервиса


@pytest.mark.django_db
def test_patch_is_closed_without_write_level(client, pair):
    assert patch_json(client, f"{BASE}/companies/hi-tech-group", {"name": "X"},
                      **auth(token())).status_code == 403


@pytest.mark.django_db(transaction=True)
def test_archive_and_restore_are_platform_operations(client, two_companies):
    alpha, beta = two_companies
    # staff — админ платформы «широкого» толка, но не суперпользователь: 403.
    assert client.post(f"{BASE}/companies/{alpha}/archive",
                       **auth(staff_token())).status_code == 403

    res = client.post(f"{BASE}/companies/{alpha}/archive", **auth(superuser_token()))
    assert res.status_code == 200
    assert res.json()["status"] == "archived"
    assert res.json()["archived_at"] is not None

    # Повтор — идемпотентно, 200 с тем же состоянием.
    assert client.post(f"{BASE}/companies/{alpha}/archive",
                       **auth(superuser_token())).status_code == 200

    # beta теперь единственная действующая — гейт режима перехода.
    res = client.post(f"{BASE}/companies/{beta}/archive", **auth(superuser_token()))
    assert res.status_code == 409
    assert res.json()["code"] == "last_active"
    assert Company.objects.get(slug=beta).status == CompanyStatus.ACTIVE

    res = client.post(f"{BASE}/companies/{alpha}/restore", **auth(superuser_token()))
    assert res.status_code == 200
    assert res.json()["status"] == "active"
    assert res.json()["archived_at"] is None
