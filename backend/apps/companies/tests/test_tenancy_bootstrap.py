"""Одноразовый перенос существующих hr/tasks/contracts/signoff в схему компании.

Тесты физически переносят БОЕВЫЕ таблицы тестовой БД (``ALTER TABLE ... SET
SCHEMA``) — это не изолированная песочница, а те самые ``hr_employee``,
``tasks_task`` и т.д., которыми пользуются тесты apps.hr/apps.tasks/
apps.contracts/apps.signoff. Идут с ``transaction=True``: DDL из нескольких
операторов подряд обычный ``django_db`` откатил бы между шагами, а не после
теста целиком.

Уборка — САМАЯ важная часть этого файла, важнее самих проверок. Если она не
вернёт таблицы обратно в public, весь ОСТАЛЬНОЙ набор тестов в сборке не
найдёт своих таблиц — это не "осиротевшая схема", а сломанная тестовая база
для всех, кто запускает `pytest` после этого файла. Реализация уборки —
``_tenancy_test_support.restore_public`` (общая с ``test_migrate_shared.py``):
переносит найденные в схеме компании таблицы и строки ``django_migrations``
обратно в public тем же инструментом (``ALTER TABLE ... SET SCHEMA`` /
INSERT), каким их туда забрала команда, и только потом сносит опустевшую
схему — НЕ голый ``schema_service.drop_schema``, тот снёс бы перенесённые
таблицы ВМЕСТЕ со схемой каскадом.

Фикстура ``cleanup`` — autouse и вызывает ``restore_public()`` в teardown
(после ``yield``): pytest гарантирует, что код после ``yield`` отработает,
даже если сам тест упал на assert — это и есть защита от "половина таблиц
осталась в чужой схеме".

Оракул полноты переноса (``_tenancy_test_support.public_tenant_leftovers``)
намеренно не использует Django-реестр моделей: он читает Postgres напрямую
по имени таблицы. Если бы тест сверял результат со списком, добытым ТОЙ ЖЕ
функцией, что и сама команда (``Command._tenant_tables``), он доказывал бы
только то, что команда перенесла ровно то, что сама решила переносить, а не
то, что перенос полон — ровно так остался бы незамеченным пропуск
auto-created M2M-таблицы (``tasks_task_labels``, поле без ``through``),
которую ``get_models()`` без ``include_auto_created=True`` не возвращает.
"""

import pytest
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection

import apps.companies.management.commands.tenancy_bootstrap as tenancy_bootstrap
from apps.companies.models import Company
from apps.companies.services import schema_service
from apps.companies.tests._tenancy_test_support import (
    public_tenant_leftovers,
    restore_public,
)
from htqweb.tenancy.context import schema_for

SLUG = "t-root"
SCHEMA = schema_for(SLUG)


def _schema_of(table: str) -> str | None:
    """Схема таблицы (НЕ вьюхи — ``holding`` держит одноимённые вьюхи)."""
    with connection.cursor() as cur:
        cur.execute(
            "SELECT table_schema FROM information_schema.tables "
            "WHERE table_name = %s AND table_type = 'BASE TABLE'",
            [table],
        )
        row = cur.fetchone()
        return row[0] if row else None


@pytest.fixture(autouse=True)
def cleanup():
    yield
    restore_public(SLUG)


@pytest.mark.django_db(transaction=True)
def test_dry_run_changes_nothing():
    call_command("tenancy_bootstrap", slug=SLUG, name="Корень",
                 kind="holding", dry_run=True)
    assert not Company.objects.filter(slug=SLUG).exists()
    assert not schema_service.schema_exists(SLUG)
    assert _schema_of("tasks_task") == "public"
    assert _schema_of("hr_employee") == "public"


@pytest.mark.django_db(transaction=True)
def test_dry_run_works_even_if_company_already_exists():
    """Разведка — не разрушающее действие, поэтому одноразовость её не касается.

    Если бы --dry-run сначала проверял отсутствие компании, разведку нельзя
    было бы прогнать на уже переехавшей базе — а это ровно тот случай, когда
    оператору она нужнее всего (проверить состояние ПОСЛЕ переноса).
    """
    Company.objects.create(slug=SLUG, name="Корень", kind="holding")
    call_command("tenancy_bootstrap", slug=SLUG, name="Корень",
                 kind="holding", dry_run=True)
    assert _schema_of("tasks_task") == "public"


@pytest.mark.django_db(transaction=True)
def test_moves_tenant_tables_out_of_public():
    call_command("tenancy_bootstrap", slug=SLUG, name="Корень", kind="holding")
    assert _schema_of("tasks_task") == SCHEMA
    assert _schema_of("hr_employee") == SCHEMA
    assert _schema_of("contracts_budget") == SCHEMA
    assert _schema_of("signoff_approvalprocess") == SCHEMA

    # Полнота переноса — по факту Postgres (см. докстринг модуля), а не по
    # тому же реестру моделей, которым пользуется сама команда: в public не
    # должно остаться НИ ОДНОЙ таблицы с именем тенантной аппки, включая
    # auto-created M2M вроде tasks_task_labels.
    assert public_tenant_leftovers() == set()


@pytest.mark.django_db(transaction=True)
def test_leaves_shared_tables_in_public():
    call_command("tenancy_bootstrap", slug=SLUG, name="Корень", kind="holding")
    assert _schema_of("users_user") == "public"
    assert _schema_of("companies_company") == "public"


@pytest.mark.django_db(transaction=True)
def test_creates_company_row():
    call_command("tenancy_bootstrap", slug=SLUG, name="Корень", kind="holding")
    company = Company.objects.get(slug=SLUG)
    assert company.name == "Корень"
    assert company.kind == "holding"


@pytest.mark.django_db(transaction=True)
def test_migration_state_travels_with_the_tables():
    """Строки django_migrations для перенесённых аппок обязаны И появиться в
    схеме компании, И пропасть из public — иначе migrate_companies решит,
    что схема пуста, и попробует создать таблицы поверх уже существующих
    (или наоборот: manage.py migrate в public продолжит считать тенантные
    аппки мигрированными при отсутствующих там таблицах).
    """
    with connection.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT app FROM public.django_migrations WHERE app = ANY(%s)",
            [list(settings.TENANT_APPS)],
        )
        before = {row[0] for row in cur.fetchall()}
    assert before == {"hr", "tasks", "contracts", "signoff"}, (
        "предусловие теста: до переноса тенантные аппки обязаны быть "
        "мигрированы в public — иначе тест ничего не доказывает"
    )

    call_command("tenancy_bootstrap", slug=SLUG, name="Корень", kind="holding")

    with connection.cursor() as cur:
        cur.execute(f"SELECT DISTINCT app FROM {SCHEMA}.django_migrations")
        apps_in_schema = {row[0] for row in cur.fetchall()}
    assert apps_in_schema == {"hr", "tasks", "contracts", "signoff"}

    with connection.cursor() as cur:
        cur.execute(
            "SELECT app FROM public.django_migrations WHERE app = ANY(%s)",
            [list(settings.TENANT_APPS)],
        )
        left_in_public = {row[0] for row in cur.fetchall()}
    assert left_in_public == set(), (
        "строки миграций тенантных аппок не должны оставаться в public "
        "после переноса"
    )


@pytest.mark.django_db(transaction=True)
def test_rejects_duplicate_slug():
    Company.objects.create(slug=SLUG, name="Уже есть", kind="holding")
    with pytest.raises(CommandError):
        call_command("tenancy_bootstrap", slug=SLUG, name="Дубль", kind="holding")

    # До любых разрушающих действий: таблицы обязаны остаться на месте.
    assert _schema_of("tasks_task") == "public"
    assert not schema_service.schema_exists(SLUG)


@pytest.mark.django_db(transaction=True)
def test_rejects_invalid_slug():
    with pytest.raises(CommandError):
        call_command("tenancy_bootstrap", slug="Плохой_Slug", name="X", kind="holding")

    assert _schema_of("tasks_task") == "public"
    assert not Company.objects.filter(slug="Плохой_Slug").exists()


@pytest.mark.django_db(transaction=True)
def test_rebuilds_holding_views_after_bootstrap():
    """После bootstrap'а компания одна и уже действующая — сводки обязаны
    её видеть, иначе первая компания осталась бы невидимой холдингу до
    первого ручного вызова migrate_companies/rebuild.
    """
    call_command("tenancy_bootstrap", slug=SLUG, name="Корень", kind="holding")

    with connection.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM information_schema.views "
            "WHERE table_schema = 'holding' AND table_name = 'tasks_task'"
        )
        assert cur.fetchone() is not None

    with connection.cursor() as cur:
        cur.execute(f"SELECT company_slug FROM holding.tasks_task "
                     f"WHERE company_slug = '{SLUG}' LIMIT 1")
        # Пустой результат валиден (задач может не быть) — важно, что запрос
        # не падает "relation does not exist": ветка UNION ALL по t-root
        # физически присутствует.
        cur.fetchall()


@pytest.mark.django_db(transaction=True)
def test_partial_failure_leaves_public_untouched(monkeypatch):
    """Сбой посреди переноса не имеет права утащить в схему компании ЧАСТЬ
    таблиц — DDL в Postgres транзакционен, и вся операция обязана быть одной
    транзакцией. Подсовываем в середину списка несуществующую таблицу: без
    transaction.atomic() алфавитно предшествующие ей таблицы уже переехали
    бы в co_t_root и остались бы там НАВСЕГДА, хотя сама команда завершилась
    бы ошибкой "relation does not exist" на выдуманной таблице.
    """
    before = public_tenant_leftovers()

    real_tenant_tables = tenancy_bootstrap.Command._tenant_tables

    def poisoned(self):
        tables = real_tenant_tables(self)
        mid = len(tables) // 2
        return tables[:mid] + ["nonexistent_table_zzz"] + tables[mid:]

    monkeypatch.setattr(tenancy_bootstrap.Command, "_tenant_tables", poisoned)
    try:
        with pytest.raises(Exception, match="nonexistent_table_zzz"):
            call_command("tenancy_bootstrap", slug=SLUG, name="Корень", kind="holding")
    finally:
        monkeypatch.undo()

    assert not Company.objects.filter(slug=SLUG).exists()
    assert not schema_service.schema_exists(SLUG)
    # Сравнение с "до", а не перебор по (потенциально патченному) реестру
    # моделей — оракул независим от того, что именно решила переносить
    # сама команда.
    assert public_tenant_leftovers() == before
