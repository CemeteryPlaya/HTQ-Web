"""Правка, архив и восстановление через HTTP: гейты и коды."""

import pytest
from django.db import connection
from django.test import Client

from apps.access.models import Role, RoleAssignment, ScopeKind
from apps.access.tests.helpers import grant as grant_permission
from apps.companies.models import Company, CompanyKind, CompanyStatus
from apps.companies.tests.api_helpers import (
    BASE, auth, headers, patch_json, staff_token, superuser_token, token,
)


def _company_write_token(user_id: int, own_slug: str) -> str:
    """Токен пользователя, у которого есть НАСТОЯЩИЙ write на ``companies`` —
    но только в СВОЕЙ компании ``own_slug``. Копия приёма из
    ``apps/access/tests/test_gate.py::_grant`` (RolePermission на голый узел
    модуля + RoleAssignment с областью «вся компания»)."""
    role = Role.objects.create(code=f"companies-writer-{user_id}", title="Реестр — запись")
    grant_permission(role, "companies", "write")
    RoleAssignment.objects.create(company_slug=own_slug, user_id=user_id, role=role,
                                  scope_kind=ScopeKind.COMPANY, scope_id=None)
    return token(user_id=user_id, sub=str(user_id), company=own_slug)


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


@pytest.mark.django_db
def test_patch_of_other_company_is_forbidden_for_company_scoped_writer(client, pair):
    """Критическая находка финального ревью: ``companies`` write в СВОЕЙ
    компании не даёт править чужую строку реестра. ``@write(...)`` считает
    уровень в компании звонящего (``hi-tech-group``) и ничего не знает про
    ``hi-tech-qazaqstan`` из URL — без ``deny_unless_platform_admin`` этот
    PATCH бы прошёл."""
    holding, htq = pair
    tok = _company_write_token(101, holding.slug)
    res = patch_json(client, f"{BASE}/companies/{htq.slug}", {"name": "Hijacked"},
                     **headers(holding.slug, tok))
    assert res.status_code == 403
    htq.refresh_from_db()
    assert htq.name == "HTQ"


@pytest.mark.django_db
def test_module_patch_of_other_company_is_forbidden_for_company_scoped_writer(client, pair):
    """Тот же разрыв на ``CompanyModuleItemView.patch`` — гейт снаружи тот же
    ``module="companies", level="write"``, поэтому владелец write в
    ``hi-tech-group`` не должен выключать модуль соседней компании."""
    holding, htq = pair
    tok = _company_write_token(102, holding.slug)
    res = patch_json(client, f"{BASE}/companies/{htq.slug}/modules/tasks",
                     {"enabled": False}, **headers(holding.slug, tok))
    assert res.status_code == 403


@pytest.mark.django_db
def test_superuser_still_writes_across_companies(client, pair):
    """Платформенный администратор не привязан к «своей» компании — новая
    проверка бьёт только company-scoped роли, не is_superuser."""
    holding, htq = pair
    res = patch_json(client, f"{BASE}/companies/{htq.slug}", {"name": "Renamed"},
                     **auth(superuser_token()))
    assert res.status_code == 200
    res = patch_json(client, f"{BASE}/companies/{htq.slug}/modules/tasks",
                     {"enabled": False}, **auth(superuser_token()))
    assert res.status_code == 200


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
