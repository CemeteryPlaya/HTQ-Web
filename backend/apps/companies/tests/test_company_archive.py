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

import pytest
from django.core.management import CommandError, call_command
from django.db import connection

from apps.companies.models import Company, CompanyStatus
from apps.companies.services import holding_views


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
