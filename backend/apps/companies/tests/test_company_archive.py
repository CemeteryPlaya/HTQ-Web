"""``manage.py company_archive`` / ``company_restore`` — правка 3 итогового ревью.

До этой правки ``status`` был обычным редактируемым полем ``CompanyAdmin``
— единственным способом заархивировать компанию, — но пересборку сводок
холдинга вызывают ровно три места (``company_create``, ``migrate_companies``,
``tenancy_bootstrap``), и правка status через админку среди них не значится.
Оператор архивировал компанию, её трафик мгновенно начинал 404-иться
(``CompanyContextMiddleware`` смотрит на ``is_active`` при каждом запросе),
но строки компании оставались в сводках холдинга до следующего
``migrate_companies`` — цифры у директоров молча включали архивную компанию.

Тесты, которые реально пересобирают представления, идут поверх
module-scoped фикстуры ``two_company_schemas`` из корневого conftest.py (та
же экономия, что описана в её докстринге — миграции тенантных аппок стоят
около минуты на схему; она же уже заводит строки реестра для обеих схем,
здесь их создавать заново не нужно). Схему ``holding`` эта общая фикстура
не знает и не трогает — её сносит local `two_companies` в ``finally``,
чтобы представления одного теста не наследовались следующим.
"""

import io

import pytest
from django.core.management import CommandError, call_command
from django.db import connection

from apps.companies.models import Company, CompanyStatus
from apps.companies.services import holding_views, lifecycle


def _drop_holding_schema() -> None:
    with connection.cursor() as cur:
        cur.execute("DROP SCHEMA IF EXISTS holding CASCADE")


def _viewdef(name: str) -> str:
    with connection.cursor() as cur:
        cur.execute("SELECT pg_get_viewdef(%s::regclass, true)", [f"holding.{name}"])
        return cur.fetchone()[0]


@pytest.fixture
def two_companies(two_company_schemas):
    """``two_company_schemas`` уже заводит строки реестра для обеих схем —
    здесь только уборка holding на выходе (сам fixture из conftest.py
    чистит только данные внутри схем компаний, про схему holding не знает)."""
    try:
        yield two_company_schemas
    finally:
        _drop_holding_schema()


@pytest.mark.django_db
def test_unknown_company_archive_is_an_error():
    with pytest.raises(CommandError):
        call_command("company_archive", "--company", "нет-такой")


@pytest.mark.django_db
def test_unknown_company_restore_is_an_error():
    with pytest.raises(CommandError):
        call_command("company_restore", "--company", "нет-такой")


@pytest.mark.django_db(transaction=True)
def test_archive_sets_status_and_archived_at(two_companies):
    alpha, _ = two_companies
    call_command("company_archive", "--company", alpha)

    company = Company.objects.get(slug=alpha)
    assert company.status == CompanyStatus.ARCHIVED
    assert company.archived_at is not None


@pytest.mark.django_db(transaction=True)
def test_restore_clears_status_and_archived_at(two_companies):
    alpha, _ = two_companies
    call_command("company_archive", "--company", alpha)
    call_command("company_restore", "--company", alpha)

    company = Company.objects.get(slug=alpha)
    assert company.status == CompanyStatus.ACTIVE
    assert company.archived_at is None


@pytest.mark.django_db(transaction=True)
def test_archived_company_drops_out_of_holding_view(two_companies):
    """Главная проверка правки: сводка холдинга обновляется СРАЗУ, а не при
    следующем migrate_companies."""
    alpha, beta = two_companies
    holding_views.rebuild_holding_views()

    call_command("company_archive", "--company", beta)

    definition = _viewdef("tasks_task")
    assert f"co_{alpha.replace('-', '_')}" in definition
    assert f"co_{beta.replace('-', '_')}" not in definition


@pytest.mark.django_db(transaction=True)
def test_restored_company_returns_to_holding_view(two_companies):
    alpha, beta = two_companies
    holding_views.rebuild_holding_views()
    call_command("company_archive", "--company", beta)

    call_command("company_restore", "--company", beta)

    definition = _viewdef("tasks_task")
    assert f"co_{alpha.replace('-', '_')}" in definition
    assert f"co_{beta.replace('-', '_')}" in definition


@pytest.mark.django_db(transaction=True)
def test_archiving_an_already_archived_company_is_idempotent(two_companies):
    """Повторный вызов — внятное сообщение, а не падение с трассировкой."""
    alpha, _ = two_companies
    call_command("company_archive", "--company", alpha)

    # Не должно упасть, а status обязан остаться прежним.
    call_command("company_archive", "--company", alpha)
    assert Company.objects.get(slug=alpha).status == CompanyStatus.ARCHIVED


@pytest.mark.django_db(transaction=True)
def test_restoring_an_already_active_company_is_idempotent(two_companies):
    alpha, _ = two_companies

    # Компания уже активна — восстановление ничего не ломает.
    call_command("company_restore", "--company", alpha)
    assert Company.objects.get(slug=alpha).status == CompanyStatus.ACTIVE


@pytest.mark.django_db
def test_migrate_companies_includes_archived_schema(two_companies):
    """Схема архива идёт в ногу с кодом (спека архива §8.1): иначе после
    первой новой миграции её не прочесть и не восстановить."""
    live, dead = list(two_companies)
    Company.objects.filter(slug=dead).update(status=CompanyStatus.ARCHIVED)
    out = io.StringIO()

    call_command("migrate_companies", "--plan", stdout=out)

    assert f"{dead}:" in out.getvalue()
    assert f"{live}:" in out.getvalue()


@pytest.mark.django_db
def test_migrate_companies_migrates_archived_and_restore_succeeds(two_companies, monkeypatch):
    """Настоящий прогон, а не --plan: схема архива мигрируется, после чего
    восстановление пересобирает сводки без ошибки. Сами миграции подменены —
    тем же приёмом, что в test_holding_views.py (схемы пула уже на текущей
    версии, а настоящий migrate_company внутри транзакции теста не нужен)."""
    from apps.companies.services import migration_service

    live, dead = list(two_companies)
    lifecycle.archive_company(dead)
    migrated = []

    def fake_migrate(slug, *, app_label=None, target=None, plan=False):
        migrated.append(slug)
        return {"applied": {}, "planned": []}

    monkeypatch.setattr(migration_service, "migrate_company", fake_migrate)
    call_command("migrate_companies", stdout=io.StringIO())

    assert sorted(migrated) == sorted([live, dead])
    company, changed = lifecycle.restore_company(dead)
    assert changed is True
    assert Company.objects.get(slug=dead).status == CompanyStatus.ACTIVE
