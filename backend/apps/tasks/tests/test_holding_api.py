"""HTTP-контракт ``GET /api/tasks/v1/holding/projects`` (блок H, задача 4).

Главное правило блока: сводка по всей группе видна ТОЛЬКО с поддомена
холдинга — даже когда у вызывающего есть управленческий доступ к домену
``tasks``. Обычная проверка домена (``request.token.is_elevated``, как у
отчётов по персоналу) знает только флаги ВЫЗЫВАЮЩЕГО и ничего не знает про
ВИД его компании, поэтому вьюха обязана сверить это сама
(``views._deny_unless_holding``) — тесты ниже бьют именно по этому шву.

«Управленческий доступ» здесь — ``is_staff``/``is_admin`` БЕЗ
``is_superuser`` (``token.is_elevated``). Это нарочно РАЗНЫЙ токен от
платформенного администратора (``is_superuser=True``): только последний
обязан обходить проверку вида компании — руководитель дочерней компании,
даже с полным доступом к задачам, ограничен своим поддоменом.

Фикстура «две компании со схемами» — копия приёма
``apps.tasks.tests.test_holding_summary::company_schemas`` (тесты соседних
файлов не делят фикстуры друг с другом), с одной содержательной поправкой:
здесь одна компания — ``CompanyKind.HOLDING`` (поддомен, откуда сводка
обязана открываться), другая — обычная дочерняя компания группы.

Токены — копия приёма ``apps/tasks/tests/helpers.py`` с добавленным
``superuser_token``: helpers не различает staff и superuser, а этому файлу
разница принципиальна.
"""

from __future__ import annotations

import datetime

import jwt as pyjwt
import pytest
from django.conf import settings
from django.db import connection
from django.test import Client
from django.utils import timezone

from apps.companies.models import Company, CompanyKind
from apps.companies.services import holding_views, migration_service, schema_service
from htqweb.tenancy.db import use_company

BASE = "/api/tasks/v1/holding/projects"

HOLDING_SLUG = "t-api-holding"
CHILD_SLUG = "t-api-child"
SLUGS = (HOLDING_SLUG, CHILD_SLUG)


# ── токены и запросы ──────────────────────────────────────────────────────

def token(**over) -> str:
    claims = {
        "user_id": 7, "username": "u", "email": "u@htq.test",
        "is_staff": False, "is_superuser": False, "is_admin": False,
        "token_type": "access", "iat": 1, "exp": 9_999_999_999,
        "iss": "htqweb-auth", "sub": "7",
        **over,
    }
    return pyjwt.encode(claims, settings.JWT_SECRET, algorithm="HS256")


def elevated_token(**over) -> str:
    """``is_elevated`` (is_staff/is_admin), НЕ superuser — управленческий
    доступ к домену задач, но без права обойти проверку вида компании."""
    return token(is_staff=True, is_admin=True, **over)


def superuser_token(**over) -> str:
    return token(user_id=9, sub="9", is_staff=True, is_superuser=True,
                is_admin=True, **over)


def auth(tok: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {tok}"}


def headers(slug: str, tok: str) -> dict:
    """Как ставит шлюз: слаг компании в заголовке + токен, выпущенный на неё."""
    return {"HTTP_X_HTQ_COMPANY": slug, **auth(tok)}


# ── фикстура схем ─────────────────────────────────────────────────────────

def _drop_holding_schema() -> None:
    with connection.cursor() as cur:
        cur.execute("DROP SCHEMA IF EXISTS holding CASCADE")


def _truncate_company_tables() -> None:
    """``transactional_db`` чистит только public — про схемы ``co_*`` он не
    знает, а они здесь общие на весь модуль."""
    for slug in SLUGS:
        with use_company(slug, include_public=False):
            with connection.cursor() as cur:
                cur.execute(
                    "TRUNCATE tasks_dailyreport, tasks_task, tasks_project, "
                    "tasks_site, tasks_workvolumetype CASCADE"
                )


@pytest.fixture(scope="module")
def company_schemas(django_db_setup, django_db_blocker):
    """Мигрированные схемы холдинга и дочерней компании, одни на весь модуль
    (полный прогон миграций тенантных аппок стоит около минуты — см. докстринг
    ``test_holding_summary.py::company_schemas``)."""
    with django_db_blocker.unblock():
        _drop_holding_schema()
        for slug in SLUGS:
            schema_service.drop_schema(slug)
        try:
            Company.objects.create(slug=HOLDING_SLUG, name="Holding QA",
                                   kind=CompanyKind.HOLDING)
            Company.objects.create(slug=CHILD_SLUG, name="Child QA",
                                   kind=CompanyKind.SERVICE)
            for slug in SLUGS:
                schema_service.create_schema(slug)
                migration_service.migrate_company(slug)
            Company.objects.filter(slug__in=SLUGS).delete()
            yield
        finally:
            _drop_holding_schema()
            for slug in SLUGS:
                schema_service.drop_schema(slug)
            Company.objects.filter(slug__in=SLUGS).delete()


def _seed_holding(today: datetime.date) -> None:
    """Один активный проект, один активный объект, одна открытая просроченная
    задача с одним отчётом за вчера."""
    from apps.tasks.models import (
        DailyReport, Project, ProjectStatus, Site, SiteStatus, Status, Task,
        WorkVolumeType,
    )

    yesterday = today - datetime.timedelta(days=1)
    with use_company(HOLDING_SLUG):
        Project.objects.create(name="HQ Project", status=ProjectStatus.ACTIVE)
        Site.objects.create(name="HQ Site", status=SiteStatus.ACTIVE)
        task = Task.objects.create(key="HQ-1", summary="Late", status=Status.TODO,
                                   due_date=yesterday)
        valy = WorkVolumeType.objects.create(slug="valy", name="Валы")
        DailyReport.objects.create(task=task, volume_type=valy, quantity=5,
                                   work_date=yesterday)


def _seed_child(today: datetime.date) -> None:
    """Два активных проекта, два объекта (один закрыт), три задачи (две
    открытые, из них ни одной просроченной; одна done) и ни одного отчёта —
    иные числа, чем у холдинга, чтобы сложение строк в тесте totals было
    содержательным."""
    from apps.tasks.models import Project, ProjectStatus, Site, SiteStatus, Status, Task

    tomorrow = today + datetime.timedelta(days=1)
    with use_company(CHILD_SLUG):
        Project.objects.create(name="Child A", status=ProjectStatus.ACTIVE)
        Project.objects.create(name="Child B", status=ProjectStatus.ACTIVE)
        Site.objects.create(name="Child Site", status=SiteStatus.ACTIVE)
        Site.objects.create(name="Child Closed", status=SiteStatus.CLOSED)
        Task.objects.create(key="CH-1", summary="Open 1", status=Status.TODO,
                            due_date=tomorrow)
        Task.objects.create(key="CH-2", summary="Open 2", status=Status.IN_PROGRESS)
        Task.objects.create(key="CH-3", summary="Finished", status=Status.DONE,
                            due_date=today - datetime.timedelta(days=5))


@pytest.fixture
def today() -> datetime.date:
    return timezone.localdate()


@pytest.fixture
def two_companies(db, company_schemas, today):
    """Холдинг + дочерняя компания, наполненные данными, со свежими вьюхами."""
    Company.objects.create(slug=HOLDING_SLUG, name="Holding QA", kind=CompanyKind.HOLDING)
    Company.objects.create(slug=CHILD_SLUG, name="Child QA", kind=CompanyKind.SERVICE)
    _seed_holding(today)
    _seed_child(today)
    holding_views.rebuild_holding_views()
    try:
        yield
    finally:
        _drop_holding_schema()
        _truncate_company_tables()


@pytest.fixture
def client():
    return Client()


# ── auth: без токена ────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_requires_jwt_at_all(client):
    assert client.get(BASE).status_code == 401


# ── главное правило блока ───────────────────────────────────────────────────

@pytest.mark.django_db(transaction=True)
def test_holding_subdomain_with_elevated_access_returns_200_with_companies(
    client, two_companies,
):
    resp = client.get(BASE, **headers(HOLDING_SLUG, elevated_token(company=HOLDING_SLUG)))
    assert resp.status_code == 200
    body = resp.json()
    assert {row["company_slug"] for row in body["companies"]} == set(SLUGS)


@pytest.mark.django_db(transaction=True)
def test_child_subdomain_is_forbidden_even_with_elevated_access(client, two_companies):
    """Главный тест блока: управленческий доступ есть (тот же токен, что и
    выше), но поддомен — дочерней компании, а не холдинга. Обязан быть 403,
    а не 200."""
    resp = client.get(BASE, **headers(CHILD_SLUG, elevated_token(company=CHILD_SLUG)))
    assert resp.status_code == 403


@pytest.mark.django_db(transaction=True)
def test_plain_user_is_forbidden(client, two_companies):
    """Обычный токен без управленческих флагов — 403 ещё до проверки вида
    компании (та же ``PermissionDenied`` → ``"Forbidden"``, что у отчётов по
    персоналу), сводка сервиса вообще не вызывается."""
    resp = client.get(BASE, **headers(HOLDING_SLUG, token(company=HOLDING_SLUG)))
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Forbidden"


@pytest.mark.django_db(transaction=True)
def test_platform_admin_gets_200_from_child_subdomain(client, two_companies):
    """Платформенный администратор (``is_superuser``, не просто ``is_staff``)
    проходит всегда, даже с поддомена, с которого сводка обычному
    руководителю недоступна."""
    resp = client.get(BASE, **headers(CHILD_SLUG, superuser_token(company=CHILD_SLUG)))
    assert resp.status_code == 200
    body = resp.json()
    assert {row["company_slug"] for row in body["companies"]} == set(SLUGS)


# ── форма ответа ─────────────────────────────────────────────────────────

@pytest.mark.django_db(transaction=True)
def test_company_name_comes_from_the_registry(client, two_companies):
    resp = client.get(BASE, **headers(HOLDING_SLUG, elevated_token(company=HOLDING_SLUG)))
    body = resp.json()
    names = {row["company_slug"]: row["company_name"] for row in body["companies"]}
    assert names[HOLDING_SLUG] == "Holding QA"
    assert names[CHILD_SLUG] == "Child QA"
    for name in names.values():
        assert name  # непусто — имена приезжают из реестра, а не только слаги


@pytest.mark.django_db(transaction=True)
def test_missing_registry_row_falls_back_to_slug_instead_of_500(
    client, two_companies, monkeypatch,
):
    """``get_company`` документированно отдаёт ``None``, если строки реестра
    уже нет — окно реальное: представления холдинга зафиксированы до
    следующей пересборки, а строка ``Company`` может исчезнуть раньше
    (осиротевшая строка после неудачного отката ``company_create``, см.
    CLAUDE.md), плюс 5-секундный TTL его кэша. Слепое индексирование
    ``get_company(slug)["name"]`` дало бы ``TypeError`` мимо единственного
    ``except`` — голый 500 без конверта ``{"detail": ...}``. Ручка обязана
    остаться 200: цифры по компании настоящие, отсутствует только вывеска."""
    from apps.companies import interface as companies_interface

    real_get_company = companies_interface.get_company

    def fake_get_company(slug):
        return None if slug == CHILD_SLUG else real_get_company(slug)

    monkeypatch.setattr(companies_interface, "get_company", fake_get_company)

    resp = client.get(BASE, **headers(HOLDING_SLUG, elevated_token(company=HOLDING_SLUG)))
    assert resp.status_code == 200
    names = {row["company_slug"]: row["company_name"] for row in resp.json()["companies"]}
    assert names[CHILD_SLUG] == CHILD_SLUG       # вывеска пропала — остался слаг
    assert names[HOLDING_SLUG] == "Holding QA"   # у остальных строк имя как обычно


@pytest.mark.django_db(transaction=True)
def test_row_shape_and_dates_are_iso_strings(client, two_companies, today):
    """Дата последнего отчёта уезжает ISO-строкой (pydantic ``mode="json"``),
    а у компании без отчётов — ``null``, не сегодняшняя дата."""
    resp = client.get(BASE, **headers(HOLDING_SLUG, elevated_token(company=HOLDING_SLUG)))
    rows = {row["company_slug"]: row for row in resp.json()["companies"]}
    assert set(rows[HOLDING_SLUG]) == {
        "company_slug", "company_name", "projects_active", "sites_active",
        "tasks_open", "tasks_overdue", "reports_last_date",
    }
    yesterday = today - datetime.timedelta(days=1)
    assert rows[HOLDING_SLUG]["reports_last_date"] == yesterday.isoformat()
    assert rows[CHILD_SLUG]["reports_last_date"] is None


@pytest.mark.django_db(transaction=True)
def test_totals_equal_the_sum_of_the_rows(client, two_companies):
    """Числа посчитаны вручную по фикстуре, а не тем же выражением, что в
    сервисе: holding — 1 проект/1 объект/1 открытая просроченная; child — 2
    проекта/1 активный объект/2 открытых, 0 просроченных."""
    resp = client.get(BASE, **headers(HOLDING_SLUG, elevated_token(company=HOLDING_SLUG)))
    body = resp.json()

    rows = body["companies"]
    manual_totals = {
        "projects_active": sum(r["projects_active"] for r in rows),
        "sites_active": sum(r["sites_active"] for r in rows),
        "tasks_open": sum(r["tasks_open"] for r in rows),
        "tasks_overdue": sum(r["tasks_overdue"] for r in rows),
    }
    assert body["totals"] == manual_totals
    # Фикстура содержательна: не всё нулями.
    assert manual_totals == {
        "projects_active": 3, "sites_active": 2,
        "tasks_open": 3, "tasks_overdue": 1,
    }


# ── представления снесены ────────────────────────────────────────────────

@pytest.mark.django_db(transaction=True)
def test_views_gone_returns_503_not_500_not_200_with_zeros(client, two_companies):
    holding_views.drop_holding_views()
    resp = client.get(BASE, **headers(HOLDING_SLUG, elevated_token(company=HOLDING_SLUG)))
    assert resp.status_code == 503
    assert isinstance(resp.json()["detail"], str)


# ── оба написания пути (APPEND_SLASH=False) ─────────────────────────────────

@pytest.mark.django_db(transaction=True)
def test_both_path_spellings_respond(client, two_companies):
    tok = elevated_token(company=HOLDING_SLUG)
    for path in (BASE, f"{BASE}/"):
        resp = client.get(path, **headers(HOLDING_SLUG, tok))
        assert resp.status_code != 404, path
