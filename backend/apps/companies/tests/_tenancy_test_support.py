"""Общие помощники для тестов, которые физически двигают public-таблицы.

Не файл с тестами (без префикса ``test_``, pytest его не собирает) —
переиспользуется и `test_tenancy_bootstrap.py`, и `test_migrate_shared.py`:
оба сценария создают компанию через `tenancy_bootstrap` и обязаны убрать за
собой одинаково надёжно.

``restore_public`` — симметричный откат переноса, а НЕ
`schema_service.drop_schema` напрямую: `DROP SCHEMA ... CASCADE` снёс бы
перенесённые таблицы ВМЕСТЕ со схемой, а не вернул бы их в `public` — то
есть первый же прогон необратимо стёр бы боевые таблицы тестовой БД. Состав
схемы читается по факту (`information_schema`), а не по списку тенантных
моделей — иначе уборка повторила бы ту же ошибку, от которой защищает
(предположение, что перенос прошёл целиком).

``public_tenant_leftovers`` — оракул для тестов, который НЕ вызывает
`Command._tenant_tables`/`get_models()`: чистый факт Postgres по имени
таблицы. Если бы тест сверял результат переноса со списком, добытым ТОЙ ЖЕ
функцией, что и сама команда, он доказывал бы только то, что команда
перенесла ровно то, что сама решила переносить — а не то, что перенос полон
(см. регресс с auto-created M2M-таблицей `tasks_task_labels`, пропущенной
`get_models()` по умолчанию).

Владелец таблицы определяется по САМОМУ ДЛИННОМУ совпадающему префиксу среди
реально установленных app_label (``django_apps.get_app_configs()``), а не
наивным ``table_name.startswith(f"{label}_")`` по одним только
TENANT_APPS: label аппки сам может содержать подчёркивание и оказаться
префиксом другого label. Пример из этой же кодовой базы —
``apps/signoff/tests/testapp/apps.py`` регистрирует тестовую аппку с
label ``"signoff_testapp"`` (только в `INSTALLED_APPS` тестов), её таблица
``signoff_testapp_probedoc`` наивно тоже проходит по префиксу ``"signoff_"``,
хотя к тенантной аппке `signoff` не имеет отношения и никогда не должна
переезжать. Самый длинный префикс разрешает это верно: `"signoff_testapp"`
длиннее и совпадает точнее, чем `"signoff"`.
"""

from __future__ import annotations

from django.apps import apps as django_apps
from django.conf import settings
from django.db import connection, transaction
from psycopg import sql

from apps.companies.models import Company
from apps.companies.services import holding_views, schema_service
from htqweb.tenancy.context import schema_for


def _owning_app_label(table: str, labels_longest_first: list[str]) -> str | None:
    """Чей это стол по имени — самый длинный совпадающий label, иначе None."""
    for label in labels_longest_first:
        if table.startswith(f"{label}_"):
            return label
    return None


def public_tenant_leftovers() -> set[str]:
    """Таблицы тенантных аппок, всё ещё торчащие в public — по имени.

    Владелец ищется по самому длинному совпадающему label среди РЕАЛЬНО
    установленных аппок (см. докстринг модуля про ``signoff_testapp``), а не
    голым префиксом из TENANT_APPS — иначе более специфичная нетенантная
    аппка с похожим label ложно засчиталась бы тенантной.
    """
    labels_longest_first = sorted(
        (cfg.label for cfg in django_apps.get_app_configs()),
        key=len, reverse=True,
    )
    tenant = set(settings.TENANT_APPS)
    with connection.cursor() as cur:
        cur.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
        )
        tables = [row[0] for row in cur.fetchall()]
    return {
        table for table in tables
        if _owning_app_label(table, labels_longest_first) in tenant
    }


def restore_public(slug: str) -> None:
    """Вернуть таблицы и состояние миграций схемы компании обратно в public.

    Одна `transaction.atomic()` на весь возврат — тем же аргументом, что и
    у самой команды (DDL в Postgres транзакционен, частичная уборка хуже её
    отсутствия): либо вернулось всё, либо ничего, и следующий тест не
    получит схему в непонятном промежуточном состоянии.
    """
    schema = schema_for(slug)
    if not schema_service.schema_exists(slug):
        Company.objects.filter(slug=slug).delete()
        return

    with transaction.atomic(), connection.cursor() as cur:
        cur.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = %s AND table_name != 'django_migrations'",
            [schema],
        )
        tables = [row[0] for row in cur.fetchall()]
        for table in tables:
            cur.execute(
                sql.SQL("ALTER TABLE {}.{} SET SCHEMA public").format(
                    sql.Identifier(schema), sql.Identifier(table),
                )
            )

        cur.execute("SELECT to_regclass(%s)", [f"{schema}.django_migrations"])
        if cur.fetchone()[0] is not None:
            cur.execute(
                sql.SQL(
                    "INSERT INTO public.django_migrations (app, name, applied) "
                    "SELECT app, name, applied FROM {}.django_migrations AS moved "
                    "WHERE NOT EXISTS ("
                    "  SELECT 1 FROM public.django_migrations AS existing "
                    "  WHERE existing.app = moved.app AND existing.name = moved.name"
                    ")"
                ).format(sql.Identifier(schema))
            )

    # Схема компании пуста (таблицы разъехались по public выше) — можно
    # безопасно сносить её CASCADE, но снос холдинга сначала: он мог
    # собраться поверх этой схемы, и DROP SCHEMA ... CASCADE утащил бы вьюхи
    # holding, оставив её в неопределённом состоянии для следующего теста.
    holding_views.drop_holding_views()
    schema_service.drop_schema(slug)
    Company.objects.filter(slug=slug).delete()
    holding_views.rebuild_holding_views()
