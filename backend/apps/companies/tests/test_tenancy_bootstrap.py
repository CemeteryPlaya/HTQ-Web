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
для всех, кто запускает `pytest` после этого файла.

Поэтому уборка НЕ идёт через ``schema_service.drop_schema`` напрямую: DROP
SCHEMA ... CASCADE снёс бы перенесённые таблицы ВМЕСТЕ со схемой, а не
вернул бы их в public — ровно та ошибка, которую этот докстринг предупреждает
не совершать. Вместо этого ``_restore_public`` переносит найденные в схеме
компании таблицы и строки ``django_migrations`` обратно в public тем же
инструментом (``ALTER TABLE ... SET SCHEMA`` / INSERT), каким их туда забрала
команда, и только потом сносит опустевшую схему. Она читает состав схемы
компании через ``information_schema`` вместо того, чтобы полагаться на
список тенантных моделей — так уборка остаётся верной даже если перенос
запнулся на середине (что не должно происходить благодаря
``transaction.atomic()`` внутри команды, но проверяется отдельным тестом
ниже, а не только предполагается).

Фикстура ``cleanup`` — autouse и вызывает ``_restore_public()`` в teardown
(после ``yield``): pytest гарантирует, что код после ``yield`` отработает,
даже если сам тест упал на assert — это и есть защита от "половина таблиц
осталась в чужой схеме".
"""

import pytest
from django.apps import apps as django_apps
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from psycopg import sql

import apps.companies.management.commands.tenancy_bootstrap as tenancy_bootstrap
from apps.companies.models import Company
from apps.companies.services import holding_views, schema_service
from htqweb.tenancy.context import schema_for

SLUG = "t-root"
SCHEMA = schema_for(SLUG)


def _tenant_tables() -> list[str]:
    tables = []
    for label in settings.TENANT_APPS:
        for model in django_apps.get_app_config(label).get_models():
            tables.append(model._meta.db_table)
    return sorted(tables)


def _schema_of(table: str) -> str | None:
    with connection.cursor() as cur:
        cur.execute(
            "SELECT table_schema FROM information_schema.tables WHERE table_name = %s",
            [table],
        )
        row = cur.fetchone()
        return row[0] if row else None


def _restore_public() -> None:
    """Вернуть всё, что нашлось в схеме компании, обратно в public.

    Состав схемы читается по факту (``information_schema``), а не по списку
    тенантных моделей — иначе уборка сама повторила бы ту же ошибку, от
    которой защищает: предположение, что перенос прошёл целиком.
    """
    if not schema_service.schema_exists(SLUG):
        Company.objects.filter(slug=SLUG).delete()
        return

    with connection.cursor() as cur:
        cur.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = %s AND table_name != 'django_migrations'",
            [SCHEMA],
        )
        tables = [row[0] for row in cur.fetchall()]
        for table in tables:
            cur.execute(
                sql.SQL("ALTER TABLE {}.{} SET SCHEMA public").format(
                    sql.Identifier(SCHEMA), sql.Identifier(table),
                )
            )

        cur.execute("SELECT to_regclass(%s)", [f"{SCHEMA}.django_migrations"])
        if cur.fetchone()[0] is not None:
            cur.execute(
                sql.SQL(
                    "INSERT INTO public.django_migrations (app, name, applied) "
                    "SELECT app, name, applied FROM {}.django_migrations AS moved "
                    "WHERE NOT EXISTS ("
                    "  SELECT 1 FROM public.django_migrations AS existing "
                    "  WHERE existing.app = moved.app AND existing.name = moved.name"
                    ")"
                ).format(sql.Identifier(SCHEMA))
            )

    # Схема компании пуста (таблицы разъехались по public выше) — можно
    # безопасно сносить её CASCADE, но снос холдинга сначала: он мог
    # собраться поверх этой схемы (тест rebuild), и DROP SCHEMA ... CASCADE
    # утащил бы вьюхи holding, оставив её в неопределённом состоянии для
    # следующего теста.
    holding_views.drop_holding_views()
    schema_service.drop_schema(SLUG)
    Company.objects.filter(slug=SLUG).delete()
    holding_views.rebuild_holding_views()


@pytest.fixture(autouse=True)
def cleanup():
    yield
    _restore_public()


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

    # Полнота переноса — не выборочная проверка двух-трёх таблиц: каждая
    # модель тенантных аппок обязана оказаться в схеме компании.
    for table in _tenant_tables():
        assert _schema_of(table) == SCHEMA, f"{table} не переехала в {SCHEMA}"


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
    for table in _tenant_tables():
        assert _schema_of(table) == "public", f"{table} не осталась в public"
