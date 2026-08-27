"""Прогон миграций по схемам компаний.

Тесты, которые действительно мигрируют, идут с ``transaction=True``:
миграции — это DDL, выполняемый многими операторами подряд, и обычный
обёрнутый в atomic тест откатил бы половину сделанного между шагами. Платой
за это является ручная уборка — схему за таким тестом никто не откатывает,
поэтому ``drop_schema`` в фикстуре обязателен. Тесты сухого прогона и
разбора аргументов обходятся обычным ``django_db``: они ничего не создают,
и откат транзакции убирает за ними всё сам.
"""

import io

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection

from apps.companies.models import Company, CompanyKind, CompanySchemaVersion
from apps.companies.services import migration_service, schema_service


def _company(slug: str, name: str) -> Company:
    company = Company.objects.create(slug=slug, name=name, kind=CompanyKind.SERVICE)
    # Уборка на входе, а не только на выходе: схема, оставшаяся от прогона,
    # который упал до teardown, иначе делала бы следующий прогон зелёным по
    # чужим таблицам.
    schema_service.drop_schema(slug)
    schema_service.create_schema(slug)
    return company


@pytest.fixture
def alpha(db):
    company = _company("t-alpha", "Alpha")
    yield company
    schema_service.drop_schema("t-alpha")


@pytest.fixture
def beta(db):
    company = _company("t-beta", "Beta")
    yield company
    schema_service.drop_schema("t-beta")


def _tables_in(schema: str) -> set[str]:
    with connection.cursor() as cur:
        cur.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = %s",
            [schema],
        )
        return {row[0] for row in cur.fetchall()}


def _migration_rows(schema: str) -> set[tuple[str, str]]:
    """Содержимое django_migrations КОНКРЕТНОЙ схемы.

    Имя схемы подставляется в SQL, а не передаётся параметром: имя таблицы
    плейсхолдером не задаётся. Значения приходят только из этого модуля.
    """
    if "django_migrations" not in _tables_in(schema):
        return set()
    with connection.cursor() as cur:
        cur.execute(f'SELECT app, name FROM "{schema}".django_migrations')
        return {(row[0], row[1]) for row in cur.fetchall()}


@pytest.mark.django_db(transaction=True)
def test_migrate_creates_tenant_tables_in_company_schema(alpha):
    migration_service.migrate_company("t-alpha")
    tables = _tables_in("co_t_alpha")
    assert "hr_employee" in tables
    assert "tasks_task" in tables
    assert "contracts_counterparty" in tables


@pytest.mark.django_db(transaction=True)
def test_each_schema_gets_its_own_migration_state(alpha, beta):
    """Ключевая деталь всей задачи.

    Если во время миграции Django находит public.django_migrations и пишет
    состояние туда, ВСЕ компании начинают считать себя мигрированными
    вместе, а их схемы остаются пустыми. Проверяется в трёх местах сразу:
    состояние легло в схему компании, public не изменился, и вторая
    компания после прогона первой по-прежнему считает себя непромигрированной.
    """
    public_before = _migration_rows("public")

    migration_service.migrate_company("t-alpha")

    alpha_rows = _migration_rows("co_t_alpha")
    assert any(app == "hr" for app, _ in alpha_rows)
    assert _migration_rows("public") == public_before

    # Вторая компания не «промигрировалась» заодно с первой.
    assert migration_service.migrate_company("t-beta", plan=True)["planned"]
    migration_service.migrate_company("t-beta")
    assert "hr_employee" in _tables_in("co_t_beta")


@pytest.mark.django_db(transaction=True)
def test_migrate_does_not_touch_shared_apps(alpha):
    """users/cms/media_files живут в public и в схему компании не копируются.

    django_celery_beat попадает сюда же, хотя формально он ЗАВИСИМОСТЬ двух
    тенантных миграций (hr.0019, tasks.0003 заводят периодические задачи):
    расписание у платформы одно на всех, beat читает его из public, и вторая
    копия таблицы в схеме компании была бы мёртвым грузом.
    """
    migration_service.migrate_company("t-alpha")
    tables = _tables_in("co_t_alpha")
    assert not any(t.startswith("users_") for t in tables)
    assert not any(t.startswith("cms_") for t in tables)
    assert not any(t.startswith("django_celery_beat_") for t in tables)


@pytest.mark.django_db(transaction=True)
def test_migrate_records_version(alpha):
    migration_service.migrate_company("t-alpha")
    rows = CompanySchemaVersion.objects.filter(company=alpha)
    assert rows.count() == 4
    assert all(r.applied_migration for r in rows)
    assert all(r.last_error == "" for r in rows)
    assert all(r.last_run_at is not None for r in rows)


@pytest.mark.django_db(transaction=True)
def test_plan_mode_changes_nothing(alpha):
    result = migration_service.migrate_company("t-alpha", plan=True)
    assert result["planned"]
    assert result["applied"] == {}
    # Ни одной таблицы, включая django_migrations: сухой прогон читает
    # состояние схемы, но не заводит его.
    assert _tables_in("co_t_alpha") == set()
    assert not CompanySchemaVersion.objects.filter(company=alpha).exists()


@pytest.mark.django_db(transaction=True)
def test_second_run_is_a_noop(alpha):
    migration_service.migrate_company("t-alpha")
    result = migration_service.migrate_company("t-alpha")
    assert result["planned"] == []


@pytest.mark.django_db(transaction=True)
def test_single_app_run_pulls_in_its_tenant_dependencies(alpha):
    """``--app signoff`` тянет hr (signoff зависит от него), но не tasks.

    Сужение до одной аппки не имеет права оставить схему в состоянии,
    где таблица создана, а таблица, на которую она ссылается FK, — нет.
    """
    result = migration_service.migrate_company("t-alpha", app_label="signoff")
    tables = _tables_in("co_t_alpha")
    assert "signoff_approvalroute" in tables
    assert "hr_employee" in tables
    assert not any(t.startswith("tasks_") for t in tables)
    # hr отчитывается вместе с signoff: он реально промигрирован до той
    # версии, от которой signoff зависит, и умолчать о ней значило бы
    # оставить CompanySchemaVersion расходящимся с реальностью.
    assert "signoff" in result["applied"]
    assert "hr" in result["applied"]
    assert "tasks" not in result["applied"]


@pytest.mark.django_db
def test_missing_schema_is_an_error(db):
    """Схемы нет — прогон обязан отказаться, а не молча уйти в public.

    Postgres создаёт таблицу в ПЕРВОЙ существующей схеме search_path: если
    co_<slug> не существует, весь набор тенантных таблиц лёг бы в public
    поверх общих. Ошибка здесь дешевле разбора последствий.
    """
    Company.objects.create(slug="t-gamma", name="Gamma", kind=CompanyKind.SERVICE)
    with pytest.raises(migration_service.SchemaMissing):
        migration_service.migrate_company("t-gamma")


@pytest.mark.django_db
def test_unknown_app_is_rejected(alpha):
    with pytest.raises(ValueError):
        migration_service.migrate_company("t-alpha", app_label="cms")


@pytest.mark.django_db
def test_command_refuses_when_there_are_no_companies():
    """Пустой реестр — это ошибка команды, а не «нечего делать».

    Молчаливый успех на пустом списке скрыл бы и настоящую поломку резолва
    компаний, и опечатку в --company.
    """
    with pytest.raises(CommandError):
        call_command("migrate_companies", "--plan")


@pytest.mark.django_db
def test_command_plan_prints_pending_migrations(alpha):
    out = io.StringIO()
    call_command("migrate_companies", "--company", "t-alpha", "--plan", stdout=out)
    printed = out.getvalue()
    assert "t-alpha" in printed
    assert "hr.0001_initial" in printed


@pytest.mark.django_db
def test_command_reports_unknown_app_without_traceback(alpha):
    with pytest.raises(CommandError):
        call_command("migrate_companies", "--company", "t-alpha", "--app", "cms")
