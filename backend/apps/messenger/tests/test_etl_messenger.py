"""Юнит-тесты ``manage.py etl_messenger`` (фаза 10 ETL, см. модульный
докстринг ``apps/messenger/management/commands/etl_messenger.py``).

Лёгкие: ``legacy_cursor`` замокан на ``_FakeLegacyCursor`` — фикстурные
dict-строки в памяти, БЕЗ реального psycopg-соединения с legacy-БД (эти
тесты гоняются в изоляции, см. ``apps/messenger/management/commands/
etl_messenger.py`` докстринг + бриф фазы: "НЕ бей полную сюиту — env-флак
teardown"). ``legacy_count``/``row_hash`` НЕ замоканы — это настоящие
функции ``apps.core.etl``, работающие поверх фейкового курсора (тот же
дьюк-тайпинг, что и у настоящего psycopg-курсора: ``.execute()``/
``.fetchall()``/``.fetchone()``).

Реальный прогон на копии БД (``manage.py etl_messenger [--verify]`` против
``htqweb_etl``) сделан отдельно (см. отчёт фазы) — этот файл про маппинг
колонок и идемпотентность на уровне юнит-теста, не про интеграцию с живым
legacy Postgres.
"""
from __future__ import annotations

import contextlib
import uuid
from datetime import datetime, timezone
from io import StringIO

import pytest
from django.core.management import call_command

from apps.core.etl import row_hash
from apps.messenger.management.commands import etl_messenger
from apps.messenger.models import Room, RoomParticipant

# {legacy_table: TableSpec} — переиспользуем РЕАЛЬНЫЙ ``_SPECS`` команды, а не
# копию списка полей: если поля когда-нибудь разъедутся с моделью, тест это
# заметит "бесплатно" (сверяется с тем же источником истины, что и сама ETL).
_SPEC_BY_TABLE = {s.legacy_table: s for s in etl_messenger._SPECS}


def _dt(*args) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


class _FakeLegacyCursor:
    """Дьюк-тайпинг psycopg dict-row курсора поверх фикстурных таблиц-словарей
    (``{legacy_table: [row_dict, ...]}``). Понимает ровно два вида запросов,
    которые реально шлёт ``apps/core/etl.py``/``etl_messenger.py``:
    ``SELECT count(*) ...`` (``legacy_count``) и построчный ``SELECT <cols>
    FROM "messenger"."<table>" ORDER BY ...`` (``_fetch_rows``/``_select_sql``).
    """

    def __init__(self, rows_by_table: dict[str, list[dict]]):
        self._rows_by_table = rows_by_table
        self._result: list[dict] = []

    def _table_for(self, sql: str) -> str:
        for table in self._rows_by_table:
            if f'"messenger"."{table}"' in sql:
                return table
        raise AssertionError(f"_FakeLegacyCursor: неизвестная таблица в запросе: {sql!r}")

    def execute(self, sql, params=None):
        table = self._table_for(sql)
        rows = self._rows_by_table[table]
        self._result = [{"n": len(rows)}] if "count(*)" in sql.lower() else list(rows)

    def fetchall(self):
        return list(self._result)

    def fetchone(self):
        return self._result[0] if self._result else None


@contextlib.contextmanager
def _fake_legacy_cursor(rows_by_table: dict[str, list[dict]]):
    yield _FakeLegacyCursor(rows_by_table)


def _rows_by_table(**overrides: list[dict]) -> dict[str, list[dict]]:
    """Все таблицы домена (включая пропускаемую ``chat_user_replicas``) с
    пустыми списками по умолчанию — ``overrides`` заполняет только те,
    что нужны конкретному тесту."""
    base: dict[str, list[dict]] = {
        "rooms": [], "room_participants": [], "messages": [],
        "chat_attachments": [], "audit_log": [], "user_keys": [],
        "chat_user_replicas": [],
    }
    base.update(overrides)
    return base


def _patch_cursor(monkeypatch, rows_by_table: dict[str, list[dict]]) -> None:
    monkeypatch.setattr(
        etl_messenger, "legacy_cursor",
        lambda dsn=None: _fake_legacy_cursor(rows_by_table),
    )


def _room_row(**overrides) -> dict:
    row = {
        "id": 101, "name": "General", "storage_key": uuid.uuid4(),
        "room_type": "group", "department_path": None, "is_e2ee": False,
        "avatar_url": None, "created_at": _dt(2026, 1, 1, 10, 0, 0),
        "updated_at": _dt(2026, 1, 2, 11, 30, 0),
    }
    row.update(overrides)
    return row


# ── чистая логика (без БД/мока) ──────────────────────────────────────────


def test_select_sql_casts_ltree_department_path_to_text():
    """``rooms.department_path`` — Postgres ``ltree`` в источнике (расширение
    не подключено, см. ``Room.department_path`` докстринг models.py) ->
    явный ``::text``-каст в SELECT, иначе Django CharField получил бы
    несовместимое значение от psycopg."""
    sql = etl_messenger._select_sql(_SPEC_BY_TABLE["rooms"])
    assert "department_path::text AS department_path" in sql


# ── маппинг + row_hash (contract DoD п.4) ────────────────────────────────


@pytest.mark.django_db
def test_migrate_maps_room_row_with_correct_fields_and_matching_hash(monkeypatch):
    room_row = _room_row()
    _patch_cursor(monkeypatch, _rows_by_table(rooms=[room_row]))

    call_command("etl_messenger")

    room = Room.objects.get(id=101)
    assert room.name == "General"
    assert room.storage_key == room_row["storage_key"]
    assert room.room_type == "group"
    assert room.department_path is None
    assert room.is_e2ee is False
    assert room.avatar_url is None
    assert room.created_at == room_row["created_at"]
    # auto_now обойдено (см. etl_messenger.py докстринг) — легаси-значение
    # сохранилось буквально, а не было перезаписано на "сейчас".
    assert room.updated_at == room_row["updated_at"]

    fields = _SPEC_BY_TABLE["rooms"].fields
    django_fields = {f: getattr(room, f) for f in fields}
    assert row_hash(django_fields) == row_hash(room_row)


@pytest.mark.django_db
def test_migrate_maps_room_participants_composite_pk_and_hash_matches(monkeypatch):
    room_row = _room_row()
    participant_rows = [
        {
            "room_id": 101, "user_id": 5, "role": "admin",
            "last_read_message_id": None,
            "created_at": _dt(2026, 1, 1, 10, 5, 0),
            "updated_at": _dt(2026, 1, 1, 10, 5, 0),
        },
        {
            "room_id": 101, "user_id": 6, "role": "member",
            "last_read_message_id": uuid.uuid4(),
            "created_at": _dt(2026, 1, 1, 10, 6, 0),
            "updated_at": _dt(2026, 1, 3, 9, 0, 0),
        },
    ]
    _patch_cursor(monkeypatch, _rows_by_table(
        rooms=[room_row], room_participants=participant_rows,
    ))

    call_command("etl_messenger")

    assert RoomParticipant.objects.count() == 2
    fields = _SPEC_BY_TABLE["room_participants"].fields
    for row in participant_rows:
        rp = RoomParticipant.objects.get(room_id=row["room_id"], user_id=row["user_id"])
        assert rp.role == row["role"]
        assert rp.last_read_message_id == row["last_read_message_id"]
        assert rp.updated_at == row["updated_at"]  # auto_now обойдено

        django_fields = {f: getattr(rp, f) for f in fields}
        assert row_hash(django_fields) == row_hash(row)


# ── идемпотентность ───────────────────────────────────────────────────────


@pytest.mark.django_db
def test_migrate_is_idempotent_on_second_run(monkeypatch):
    room_row = _room_row()
    _patch_cursor(monkeypatch, _rows_by_table(rooms=[room_row]))

    call_command("etl_messenger")
    call_command("etl_messenger")  # повторный прогон — тот же фейковый источник

    assert Room.objects.count() == 1
    room = Room.objects.get(id=101)
    # updated_at НЕ уехал вперёд от второго Model.save() внутри update_or_create
    # (иначе auto_now двигал бы его на каждый прогон — см. docstring файла).
    assert room.updated_at == room_row["updated_at"]


# ── --dry-run ──────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_dry_run_writes_nothing(monkeypatch):
    room_row = _room_row()
    _patch_cursor(monkeypatch, _rows_by_table(rooms=[room_row]))

    call_command("etl_messenger", dry_run=True)

    assert Room.objects.count() == 0


# ── --verify ───────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_verify_passes_when_data_matches(monkeypatch):
    room_row = _room_row()
    _patch_cursor(monkeypatch, _rows_by_table(rooms=[room_row]))
    call_command("etl_messenger")

    # Не должно бросить SystemExit — report.ok истинен (count+hash сошлись).
    call_command("etl_messenger", verify=True)


@pytest.mark.django_db
def test_verify_fails_when_target_diverges(monkeypatch):
    room_row = _room_row()
    _patch_cursor(monkeypatch, _rows_by_table(rooms=[room_row]))
    call_command("etl_messenger")

    Room.objects.filter(id=101).update(name="CORRUPTED-FOR-TEST")

    with pytest.raises(SystemExit) as exc_info:
        call_command("etl_messenger", verify=True)
    assert exc_info.value.code == 1


@pytest.mark.django_db
def test_chat_user_replicas_reported_as_skip_not_diff(monkeypatch):
    """Бриф messenger: пропуск ``chat_user_replicas`` (Р2, нет Django-цели)
    показывается в отчёте отдельной ``[SKIP]``-строкой и НЕ считается
    расхождением — итог остаётся ``ЗЕЛЁНЫЙ`` несмотря на src=1/tgt=0."""
    rows = _rows_by_table(chat_user_replicas=[{"id": 1}])
    _patch_cursor(monkeypatch, rows)

    out = StringIO()
    call_command("etl_messenger", stdout=out)
    text = out.getvalue()

    assert f"[SKIP] messenger.{etl_messenger.SKIP_TABLE}" in text
    assert etl_messenger.SKIP_NOTE in text
    assert "ИТОГ: ЗЕЛЁНЫЙ" in text
