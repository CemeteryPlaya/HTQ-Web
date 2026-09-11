"""Перевод соединения БД в схему компании.

Почему это безопасно именно здесь: CONN_MAX_AGE=0 (htqweb/settings/base.py),
то есть соединение живёт ровно один запрос и не возвращается в пул с чужим
search_path. Сброс в finally всё равно делается — чтобы поведение не зависело
от настройки, которую кто-нибудь однажды поменяет.

Имя схемы НЕ параметризуется через плейсхолдер: идентификатор в SET нельзя
передать значением. Экранирование делает psycopg-3 sql.Identifier, а набор
символов в slug дополнительно сужен валидатором в apps.companies.models.
"""

from __future__ import annotations

from contextlib import contextmanager

from django.db import connection
from psycopg import sql

from .context import (
    HOLDING_SCHEMA, current_company_or_none, reset_company, schema_for,
    set_company,
)

_PUBLIC_ONLY = sql.SQL("SET search_path TO public")


def apply_search_path(slug: str | None, *, include_public: bool = True) -> None:
    """Перевести текущее соединение в схему компании.

    ``slug=None`` возвращает соединение к чистому ``public``.
    ``include_public=False`` нужен ТОЛЬКО прогону миграций — см. докстринг
    apps.companies.services.migration_service.
    """
    if slug is None:
        statement = _PUBLIC_ONLY
    else:
        parts = [sql.Identifier(schema_for(slug))]
        if include_public:
            parts.append(sql.Identifier("public"))
        statement = sql.SQL("SET search_path TO {}").format(sql.SQL(", ").join(parts))
    with connection.cursor() as cur:
        cur.execute(statement)


@contextmanager
def use_company(slug: str, *, include_public: bool = True):
    """Выполнить блок в схеме компании, восстановив прежнее состояние.

    Восстанавливается именно ПРЕЖНЯЯ компания, а не public: вложенные
    use_company встречаются (задача обходит несколько компаний подряд), и
    выход из внутреннего блока не должен ронять внешний в public.
    """
    previous = current_company_or_none()
    token = set_company(slug)
    try:
        apply_search_path(slug, include_public=include_public)
        yield
    finally:
        reset_company(token)
        apply_search_path(previous)


@contextmanager
def use_holding():
    """Выполнить блок в схеме сводных представлений.

    Контекст компании при этом НЕ ставится: сводное чтение по определению
    находится над компаниями, и код, который его выполняет, не должен
    случайно считать себя работающим внутри одной из них.

    Путь при выходе восстанавливается в ПРЕЖНЮЮ компанию, а не в public
    (симметрично use_company): сводное чтение холдинга может выполняться
    внутри уже открытого use_company, и жёсткий сброс в public оставил бы
    contextvar и реальный search_path соединения в расхождении до конца
    внешнего блока — запросы там молча ушли бы в public вместо схемы
    компании.
    """
    previous = current_company_or_none()
    with connection.cursor() as cur:
        cur.execute(
            sql.SQL("SET search_path TO {}, public").format(
                sql.Identifier(HOLDING_SCHEMA),
            )
        )
    try:
        yield
    finally:
        apply_search_path(previous)
