"""Сводные UNION ALL-представления поверх схем всех действующих компаний.

Почему представления, а не склейка в Python: склейка ломает сортировку и
пагинацию — чтобы отдать третью страницу списка, отсортированного по сроку,
пришлось бы вытащить по три страницы из каждой схемы, слить в памяти и
отрезать. Postgres на UNION ALL строит план Append и проталкивает условия
внутрь веток, поэтому фильтр по дате не читает лишние схемы целиком.

Ограничение, принятое сознательно: в представление попадают только столбцы
модели. Компания, отставшая по миграциям и не имеющая нового столбца,
сломала бы представление — поэтому новое поле становится видно холдингу
только после того, как мигрированы все. Ловится тестом
test_view_columns_match_the_model.

Список колонок считается ОДИН раз на модель и подставляется во все ветки:
Postgres сводит ветки UNION ALL по позиции, а не по имени, и перестановка
двух столбцов совместимых типов дала бы валидное представление с
перепутанными данными — без ошибки и без единого следа.
"""

from __future__ import annotations

from django.apps import apps as django_apps
from django.conf import settings
from django.db import connection, transaction
from django.db.models import Model
from django.utils.module_loading import module_has_submodule
from psycopg import sql

from htqweb.tenancy.context import HOLDING_SCHEMA, schema_for

from ..interface import active_company_slugs

# Имя служебного столбца, по которому в сводке видно, чья это строка.
COMPANY_COLUMN = "company_slug"


def holding_models() -> list[type[Model]]:
    """Модели тенантных аппок, объявленные в apps/<домен>/holding.py.

    Автообнаружение, а не список в одном месте: иначе добавление сводимой
    модели правило бы файл в чужой аппке — та же точка конфликта, которую
    сняло автомонтирование URL по API_PREFIX.

    Модель берётся через django_apps.get_model, а не импортом
    apps.<домен>.models: прямой импорт чужих моделей запрещён и ловится
    apps/core/tests/test_app_isolation.py. Опечатка в HOLDING_MODELS даёт
    LookupError, а не молчаливый пропуск: незамеченно выпавшая из сводок
    модель — это неверные цифры у директоров, а не отсутствующая страница.
    """
    found: list[type[Model]] = []
    for config in django_apps.get_app_configs():
        if config.label not in settings.TENANT_APPS:
            continue
        if not module_has_submodule(config.module, "holding"):
            continue
        module = __import__(f"{config.name}.holding", fromlist=["holding"])
        try:
            declared = module.HOLDING_MODELS
        except AttributeError as exc:
            # Модуль есть, а объявления нет — это опечатка в имени или
            # недописанный файл. Молчаливый пропуск (getattr с дефолтом)
            # убрал бы из сводок целую аппку: цифры у директоров стали бы
            # НЕВЕРНЫМИ, а не отсутствующими, и никто бы этого не заметил.
            raise AttributeError(
                f"{config.name}.holding не объявляет HOLDING_MODELS — "
                f"аппка {config.label} молча выпала бы из сводок холдинга."
            ) from exc
        for model_name in declared:
            found.append(django_apps.get_model(config.label, model_name))
    return found


def _branch(slug: str, columns: list[sql.Identifier], table: str) -> sql.Composed:
    """Одна ветка UNION ALL: строки одной компании плюс её слаг константой.

    Слаг уходит в SQL через sql.Literal, имена схемы и таблицы — через
    sql.Identifier: в DDL плейсхолдер %s не работает, значение подставляется
    в текст запроса, поэтому экранирование обязано быть здесь.
    """
    return sql.SQL("SELECT {slug} AS {company}, {cols} FROM {schema}.{table}").format(
        slug=sql.Literal(slug),
        company=sql.Identifier(COMPANY_COLUMN),
        cols=sql.SQL(", ").join(columns),
        schema=sql.Identifier(schema_for(slug)),
        table=sql.Identifier(table),
    )


def rebuild_holding_views() -> list[str]:
    """Пересоздать все сводные представления. Идемпотентна.

    Вызывается ровно в трёх событиях: компанию создали, заархивировали,
    восстановили. Возвращает имена созданных представлений в стабильном
    порядке — на него опирается тест идемпотентности.
    """
    # fresh=True обязателен: пересборка идёт сразу после создания или
    # архивации компании, и пятисекундный кэш отдал бы список БЕЗ неё —
    # представление собралось бы без этой компании молча, без ошибки и
    # без следа в логе.
    slugs = active_company_slugs(fresh=True)
    created: list[str] = []

    # Вся пересборка — одна транзакция, потому что DDL в Postgres
    # транзакционен. Причин две. Между DROP VIEW и CREATE VIEW вьюхи не
    # существует, и в автокоммите читатель холдинга ровно в этот момент
    # получил бы «relation does not exist» на каждой пересборке. А сбой на
    # полпути (компания отстала по миграциям, см. докстринг модуля) оставил
    # бы часть представлений снесённой, часть — старой: откат возвращает
    # предыдущее, рабочее состояние целиком.
    with transaction.atomic(), connection.cursor() as cur:
        cur.execute(
            sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(
                sql.Identifier(HOLDING_SCHEMA),
            )
        )
        for model in sorted(holding_models(), key=lambda m: m._meta.db_table):
            table = model._meta.db_table
            # Столбцы — один список на модель, а не пересчёт на каждую ветку:
            # см. докстринг модуля про склейку по позиции.
            columns = [sql.Identifier(f.column) for f in model._meta.concrete_fields]
            # DROP + CREATE, а не CREATE OR REPLACE: replace умеет только
            # ДОБАВЛЯТЬ столбцы в конец, поэтому после миграции, удалившей
            # или переставившей поле, он падает — и пересборка перестала бы
            # быть идемпотентной ровно в тот момент, ради которого нужна.
            cur.execute(
                sql.SQL("DROP VIEW IF EXISTS {}.{}").format(
                    sql.Identifier(HOLDING_SCHEMA), sql.Identifier(table),
                )
            )
            if not slugs:
                # Ни одной действующей компании — представление не над чем
                # строить. Пустая вьюха с фиктивной веткой была бы хуже:
                # она бы притворялась работающей.
                continue
            body = sql.SQL(" UNION ALL ").join(
                _branch(slug, columns, table) for slug in slugs
            )
            cur.execute(
                sql.SQL("CREATE VIEW {}.{} AS {}").format(
                    sql.Identifier(HOLDING_SCHEMA), sql.Identifier(table), body,
                )
            )
            created.append(table)

    return created
