"""Сводные UNION ALL-представления поверх схем всех действующих компаний.

Почему представления, а не склейка в Python: склейка ломает сортировку и
пагинацию — чтобы отдать третью страницу списка, отсортированного по сроку,
пришлось бы вытащить по три страницы из каждой схемы, слить в памяти и
отрезать. Postgres на UNION ALL строит план Append и проталкивает условия
внутрь веток, поэтому фильтр по дате не читает лишние схемы целиком.

ГЛАВНАЯ ЦЕНА, которую платформа платит за это решение: пока представление
существует, Postgres ЗАПРЕЩАЕТ contract-миграции по его таблицам.

    ALTER TABLE t DROP COLUMN extra;
    ERROR: cannot drop column extra of table t because other objects depend on it
    ALTER TABLE t ALTER COLUMN name TYPE varchar(200);
    ERROR: cannot alter type of a column used by a view or rule

То есть любая будущая RemoveField или AlterField со сменой типа (max_length
у varchar, int -> bigint) по любой из сводимых моделей упадёт на КАЖДОЙ
компании, у которой вьюхи собраны. AddField, наоборот, проходит — то есть
блокируется ровно contract-фаза, которая по глобальному ограничению плана
обязательна.

Отсюда пара drop_holding_views / rebuild_holding_views и её единственный
штатный вызывающий — команда migrate_companies: снести до прогона миграций,
собрать после. Снос сделан отдельной функцией, а не добывается побочным
эффектом «пересборка при нуле компаний»: это самостоятельная операция, и
прятать её от вызывающего значит обречь его на подобные трюки.

Вторая цена, помельче: в представление попадают только столбцы модели.
Компания, отставшая по миграциям и не имеющая нового столбца, сломала бы
представление — поэтому новое поле становится видно холдингу только после
того, как мигрированы все. Ловится тестом test_view_columns_match_the_model.

Список колонок считается ОДИН раз на модель и подставляется во все ветки:
Postgres сводит ветки UNION ALL по позиции, а не по имени, и перестановка
двух столбцов совместимых типов дала бы валидное представление с
перепутанными данными — без ошибки и без единого следа.

Схема holding принадлежит этому модулю целиком: снос идёт по интроспекции, а
не по списку объявленных моделей. Иначе модель, убранная из HOLDING_MODELS,
оставила бы за собой представление-сироту — и оно продолжало бы блокировать
миграции по своей таблице, причём пересборка о нём бы уже не знала.
"""

from __future__ import annotations

from django.apps import apps as django_apps
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import connection, transaction
from django.db.models import Model
from django.utils.module_loading import module_has_submodule
from psycopg import sql

from htqweb.tenancy.context import HOLDING_SCHEMA, schema_for

from ..interface import active_company_slugs
from .migration_service import ADVISORY_LOCK_KEY

# Имя служебного столбца, по которому в сводке видно, чья это строка.
COMPANY_COLUMN = "company_slug"


def holding_models() -> list[type[Model]]:
    """Модели тенантных аппок, объявленные в apps/<домен>/holding.py.

    Автообнаружение, а не список в одном месте: иначе добавление сводимой
    модели правило бы файл в чужой аппке — та же точка конфликта, которую
    сняло автомонтирование URL по API_PREFIX.

    Модель берётся через django_apps.get_model, а не импортом
    apps.<домен>.models: прямой импорт чужих моделей запрещён и ловится
    apps/core/tests/test_app_isolation.py.

    Обход идёт по settings.TENANT_APPS, и объявление обязательно для КАЖДОЙ
    из них: аппке, которой сводить нечего, положено написать
    ``HOLDING_MODELS = ()`` явно. Пропуск по отсутствию файла (или атрибута)
    был бы молчаливым — целая аппка выпала бы из сводок, и цифры у
    директоров стали бы НЕВЕРНЫМИ, а не отсутствующими. Ровно тот класс
    отказа, ради которого в этом модуле нет ни одного except, глотающего
    ошибку.
    """
    found: list[type[Model]] = []
    for label in sorted(settings.TENANT_APPS):
        config = django_apps.get_app_config(label)
        if not module_has_submodule(config.module, "holding"):
            raise ImproperlyConfigured(
                f"Тенантная аппка {label!r} не объявила {config.name}.holding "
                f"и молча выпала бы из сводок холдинга. Если сводить нечего — "
                f"напишите HOLDING_MODELS = () явно."
            )
        module = __import__(f"{config.name}.holding", fromlist=["holding"])
        try:
            declared = module.HOLDING_MODELS
        except AttributeError as exc:
            # Модуль есть, а объявления нет — опечатка в имени или
            # недописанный файл. Молчаливый пропуск здесь стоит ровно того
            # же, что и отсутствие файла целиком.
            raise ImproperlyConfigured(
                f"{config.name}.holding не объявляет HOLDING_MODELS — "
                f"аппка {label} молча выпала бы из сводок холдинга."
            ) from exc
        for model_name in declared:
            found.append(django_apps.get_model(label, model_name))
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


def _lock(cur) -> None:
    """Взаимное исключение пересборок между процессами.

    Без него две пересборки, идущие параллельно (одновременная выкатка двух
    backend-web — обычное дело, см. докстринг migration_service), читают
    список компаний независимо: A увидела [x], B увидела [x, y], B
    закоммитилась первой, A легла поверх — компания y пропала из сводок БЕЗ
    ошибки и без следа в логе. Это тот же отказ, ради которого список
    читается с fresh=True; fresh закрывает кэш, но не гонку, поэтому список
    читается ПОД этой блокировкой.

    Ключ общий с migration_service: пересборка и прогон миграций по схемам
    обязаны исключать друг друга, иначе миграция упадёт на вьюхе, собранной
    параллельным процессом ровно между сносом и прогоном.

    Уровень транзакции (xact), а не сессии: снимается автоматически и на
    коммите, и на откате, поэтому упавшая пересборка не может оставить
    блокировку висеть. Advisory-локи обоих уровней живут в одном
    пространстве ключей, так что с сессионным локом migration_service этот
    конфликтует как надо.
    """
    cur.execute("SELECT pg_advisory_xact_lock(%s)", [ADVISORY_LOCK_KEY])


def _existing_views(cur) -> list[str]:
    cur.execute(
        "SELECT table_name FROM information_schema.views "
        "WHERE table_schema = %s ORDER BY table_name",
        [HOLDING_SCHEMA],
    )
    return [row[0] for row in cur.fetchall()]


def _drop_all(cur) -> list[str]:
    """Снести все представления схемы holding. Возвращает их имена."""
    dropped = _existing_views(cur)
    for table in dropped:
        cur.execute(
            sql.SQL("DROP VIEW IF EXISTS {}.{}").format(
                sql.Identifier(HOLDING_SCHEMA), sql.Identifier(table),
            )
        )
    return dropped


def drop_holding_views() -> list[str]:
    """Снести сводные представления. Идемпотентна. Возвращает снесённое.

    Нужна перед прогоном миграций по схемам компаний: существующее
    представление запрещает Postgres удалять столбцы своих таблиц и менять
    их типы (см. докстринг модуля). Парная к rebuild_holding_views.

    Холдинг без представлений — не авария, а честное отражение состояния:
    читатель получит громкую ошибку вместо цифр, собранных по
    полумигрированной группе.
    """
    with transaction.atomic(), connection.cursor() as cur:
        _lock(cur)
        return _drop_all(cur)


def rebuild_holding_views() -> list[str]:
    """Пересоздать все сводные представления. Идемпотентна.

    Вызывается ровно в трёх событиях реестра: компанию создали,
    заархивировали, восстановили — плюс после прогона миграций по схемам
    (см. докстринг модуля). Возвращает имена созданных представлений в
    стабильном порядке — на него опирается тест идемпотентности.

    Вся пересборка — одна транзакция, потому что DDL в Postgres
    транзакционен. Причин две. Между DROP VIEW и CREATE VIEW вьюхи не
    существует, и в автокоммите читатель холдинга ровно в этот момент
    получил бы «relation does not exist» на каждой пересборке. А сбой на
    полпути (компания отстала по миграциям) оставил бы часть представлений
    снесённой, часть — старой: откат возвращает предыдущее, рабочее
    состояние целиком.
    """
    created: list[str] = []

    with transaction.atomic(), connection.cursor() as cur:
        _lock(cur)
        cur.execute(
            sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(
                sql.Identifier(HOLDING_SCHEMA),
            )
        )
        # fresh=True обязателен: пересборка идёт сразу после создания или
        # архивации компании, и пятисекундный кэш отдал бы список БЕЗ неё —
        # представление собралось бы без этой компании молча, без ошибки и
        # без следа в логе. Читается ПОД блокировкой, см. _lock.
        slugs = active_company_slugs(fresh=True)
        # Снос по интроспекции и целиком: DROP + CREATE, а не
        # CREATE OR REPLACE (тот умеет только ДОБАВЛЯТЬ столбцы в конец и
        # падает ровно после contract-миграции), и не по списку моделей
        # (иначе модель, убранная из HOLDING_MODELS, оставила бы сироту).
        _drop_all(cur)
        if not slugs:
            # Ни одной действующей компании — представления не над чем
            # строить. Пустая вьюха с фиктивной веткой была бы хуже: она
            # притворялась бы работающей.
            return created
        for model in sorted(holding_models(), key=lambda m: m._meta.db_table):
            table = model._meta.db_table
            # Столбцы — один список на модель, а не пересчёт на каждую ветку:
            # см. докстринг модуля про склейку по позиции.
            columns = [sql.Identifier(f.column) for f in model._meta.concrete_fields]
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
