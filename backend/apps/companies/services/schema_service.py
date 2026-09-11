"""Создание и удаление схемы Postgres под компанию.

Только DDL самой схемы. Наполнение её таблицами — задача
migration_service.migrate_company: разделены потому, что схему создают один
раз, а мигрируют многократно.
"""

from __future__ import annotations

from django.db import connection
from psycopg import sql

from htqweb.tenancy.context import schema_for


def schema_exists(slug: str) -> bool:
    with connection.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM information_schema.schemata WHERE schema_name = %s",
            [schema_for(slug)],
        )
        return cur.fetchone() is not None


def create_schema(slug: str) -> None:
    """Создать схему компании. Идемпотентна."""
    with connection.cursor() as cur:
        cur.execute(
            sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(
                sql.Identifier(schema_for(slug)),
            )
        )


def drop_schema(slug: str) -> None:
    """Удалить схему компании со всем содержимым. Идемпотентна.

    Штатным закрытием компании НЕ является: закрытие — это архив с переносом
    активов (подпроект 4), данные при нём сохраняются. Эта функция нужна для
    отката неудавшегося создания и для уборки в тестах.
    """
    with connection.cursor() as cur:
        cur.execute(
            sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                sql.Identifier(schema_for(slug)),
            )
        )
