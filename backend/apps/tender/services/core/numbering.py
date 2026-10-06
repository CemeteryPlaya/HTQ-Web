"""Годовые номера документов модуля: ``ТН-2026-000045`` (ТЗ TND-010).

Копия ``apps/bpp/services/core/numbering.py`` на своей таблице (T-10). Одна
атомарная команда БД: строка счётчика создаётся с 1 или увеличивается,
новое значение возвращается тем же запросом. Параллельные выдачи
сериализует сама вставка по уникальному ключу (префикс, год).

Год — по «сегодня» платформы (``timezone.localdate()``, сторож
``apps/core/tests/test_platform_today.py``).
"""

from __future__ import annotations

from django.db import connection
from django.utils import timezone

from apps.tender.models import NumberSequence

#: Префикс номера тендера (ТЗ TND-010).
TENDER_PREFIX = "ТН"

_TABLE = NumberSequence._meta.db_table
_SQL = f"""
INSERT INTO {_TABLE} (prefix, year, last)
VALUES (%s, %s, 1)
ON CONFLICT (prefix, year)
DO UPDATE SET last = {_TABLE}.last + 1
RETURNING last
"""


def next_number(prefix: str, *, width: int = 6, year: int | None = None) -> str:
    year = year or timezone.localdate().year
    with connection.cursor() as cursor:
        cursor.execute(_SQL, [prefix, year])
        (value,) = cursor.fetchone()
    return f"{prefix}-{year}-{value:0{width}d}"
