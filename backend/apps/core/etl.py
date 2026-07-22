"""Общие хелперы ETL фазы 10 (перелив данных из legacy FastAPI-БД в Django).

Read-only доступ к legacy Postgres через psycopg3 + детерминированный per-row
hash для сверки count+hash. Доменные команды живут в
``apps/<домен>/management/commands/etl_<домен>.py`` и используют эти хелперы,
чтобы отчёт о сверке у всех команд был одинаковым.

Источник (legacy) — старая схема FastAPI (схемы ``cms``/``messenger``/``email``/
``media`` + public-префиксы ``hr_*``/``task_*``/``request_*`` в мн.ч., старые
имена таблиц/колонок). Цель — текущие Django-модели (``managed=True``,
имена ``<app>_<model>``). Legacy НЕ мутируется (сессия read-only).
"""
from __future__ import annotations

import contextlib
import decimal
import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, datetime, time

import psycopg
from psycopg.rows import dict_row

# DSN источника по умолчанию — копия FastAPI-данных в htqweb1-db-1 (прямой порт,
# минуя PgBouncer). Переопределяется флагом --source-dsn у каждой команды.
DEFAULT_SOURCE_DSN = "postgresql://htqweb:change-me@localhost:55432/htqweb"


@contextlib.contextmanager
def legacy_cursor(dsn: str = DEFAULT_SOURCE_DSN):
    """Курсор dict-row на legacy-БД в режиме read-only (источник не мутируется)."""
    conn = psycopg.connect(dsn, autocommit=True)
    try:
        conn.execute("SET default_transaction_read_only = on")
        with conn.cursor(row_factory=dict_row) as cur:
            yield cur
    finally:
        conn.close()


def legacy_count(cur, table: str, schema: str = "public") -> int:
    """Число строк в legacy-таблице (schema.table)."""
    cur.execute(f'SELECT count(*) AS n FROM "{schema}"."{table}"')
    return int(cur.fetchone()["n"])


def _norm(v):
    """Нормализация значения для стабильного хеша (тип-независимо)."""
    if v is None:
        return None
    if isinstance(v, (datetime, date, time)):
        return v.isoformat()
    if isinstance(v, decimal.Decimal):
        return format(v.normalize(), "f")
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (dict, list)):
        return json.dumps(v, sort_keys=True, ensure_ascii=False, default=str)
    if isinstance(v, (bytes, bytearray, memoryview)):
        return hashlib.sha256(bytes(v)).hexdigest()
    return v


def row_hash(fields: dict) -> str:
    """Стабильный SHA-256 по словарю смаппленных полей (порядок не важен).

    Обе стороны (legacy-строка и Django-объект) должны собрать ОДИНАКОВЫЙ набор
    ключей с сопоставимыми значениями — тогда хеши совпадут при верном переносе.
    """
    items = sorted((str(k), _norm(v)) for k, v in fields.items())
    blob = json.dumps(items, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


@dataclass
class TableResult:
    """Результат сверки одной таблицы: count + выборочный per-row hash."""
    name: str
    src: int
    tgt: int
    sample: int = 0          # сколько строк сверено по hash
    hash_match: int = 0      # сколько из них совпало
    note: str = ""

    @property
    def count_ok(self) -> bool:
        return self.src == self.tgt

    @property
    def hash_ok(self) -> bool:
        return self.sample == self.hash_match

    @property
    def ok(self) -> bool:
        return self.count_ok and self.hash_ok


@dataclass
class Report:
    """Единый count/hash-отчёт домена."""
    domain: str
    results: list[TableResult] = field(default_factory=list)

    def add(self, r: TableResult) -> TableResult:
        self.results.append(r)
        return r

    @property
    def ok(self) -> bool:
        return all(r.ok for r in self.results)

    def render(self) -> str:
        lines = [f"=== ETL {self.domain}: count/hash-отчёт ==="]
        for r in self.results:
            status = "OK" if r.ok else "DIFF"
            hashinfo = f"hash {r.hash_match}/{r.sample}" if r.sample else "hash -"
            extra = f"  {r.note}" if r.note else ""
            lines.append(
                f"[{status}] {r.name:<34} src={r.src:<7} tgt={r.tgt:<7} {hashinfo}{extra}"
            )
        lines.append(f"ИТОГ: {'ЗЕЛЁНЫЙ' if self.ok else 'ЕСТЬ РАСХОЖДЕНИЯ'}")
        return "\n".join(lines)
