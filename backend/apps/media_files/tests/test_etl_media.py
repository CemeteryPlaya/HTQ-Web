"""Юнит-тесты ETL media: маппинг legacy ``media.*`` -> ``apps.media_files``.

Лёгкие — НЕ гоняют полную сюиту, только этот файл, в изоляции:

    .venv/Scripts/python.exe -m pytest apps/media_files/tests/test_etl_media.py -q

``legacy_cursor`` мокается фикстурными dict-строками в памяти (без сети и
без реальной legacy-БД) — проверяем: (1) объекты создаются с верными
полями, (2) ``row_hash(legacy) == row_hash(django)`` на тех же данных,
(3) идемпотентность двойного прогона, (4) ``--dry-run`` ничего не пишет,
(5) ``--verify`` зелёный после синка и падает (``CommandError`` => код
выхода 1 из ``manage.py``) при расхождении.
"""
from __future__ import annotations

import contextlib
import uuid
from datetime import datetime, timezone

import pytest
from django.core.management import CommandError, call_command

from apps.media_files import models
from apps.media_files.management.commands import etl_media

FILE_ID_1 = uuid.UUID("11111111-1111-1111-1111-111111111111")
FILE_ID_2 = uuid.UUID("22222222-2222-2222-2222-222222222222")
VARIANT_ID_1 = uuid.UUID("33333333-3333-3333-3333-333333333333")

T1 = datetime(2026, 4, 24, 7, 7, 49, 709023, tzinfo=timezone.utc)
T2 = datetime(2026, 5, 13, 14, 44, 56, 295225, tzinfo=timezone.utc)


def _file_metadata_rows():
    return [
        {
            "id": FILE_ID_1, "path": "avatar/2026/04/f1.jpg",
            "original_filename": "photo.jpg", "owner_id": 7, "size": 2048,
            "mime": "image/jpeg", "storage_backend": "local", "is_public": False,
            "sha256": "a" * 64, "kind": "image", "scope": "avatar",
            "width": 512, "height": 512, "deleted_at": None,
            "created_at": T1, "updated_at": T1,
        },
        {
            "id": FILE_ID_2, "path": "generic/2026/04/f2.bin",
            "original_filename": "", "owner_id": None, "size": 0,
            "mime": "application/octet-stream", "storage_backend": "s3",
            "is_public": True, "sha256": None, "kind": "other", "scope": "generic",
            "width": None, "height": None, "deleted_at": T2,
            "created_at": T1, "updated_at": T2,
        },
    ]


def _file_variant_rows():
    return [
        {
            "id": VARIANT_ID_1, "file_id": FILE_ID_1, "variant": "thumb_256",
            "path": "avatar/2026/04/f1.thumb_256.jpg", "size": 512,
            "mime": "image/jpeg", "width": 256, "height": 256,
            "created_at": T2,
        },
    ]


def _audit_log_rows():
    return [
        {
            "id": 501, "user_id": 7, "action": "file_uploaded",
            "resource_type": "FileMetadata", "resource_id": str(FILE_ID_1),
            "changes": {"mime": "image/jpeg", "size": 2048},
            "ip_address": "10.0.0.1", "user_agent": "pytest/1.0",
            "correlation_id": "18d59315-cebd-4ccc-bfca-f0cd318fb6a7",
            "created_at": T1,
        },
        {
            "id": 502, "user_id": None, "action": "file_deleted",
            "resource_type": "FileMetadata", "resource_id": str(FILE_ID_2),
            "changes": None, "ip_address": None, "user_agent": None,
            "correlation_id": None, "created_at": T2,
        },
    ]


def _rows_by_table():
    return {
        "file_metadata": _file_metadata_rows(),
        "file_variants": _file_variant_rows(),
        "audit_log": _audit_log_rows(),
    }


class _FakeLegacyCursor:
    """Дублёр psycopg dict-row курсора: фикстурные строки в памяти. Ключуется
    по имени таблицы, которое встречается в SQL-запросе — все три
    legacy-таблицы называются по-разному, ложных срабатываний по подстроке
    нет."""

    def __init__(self, rows_by_table):
        self._rows_by_table = rows_by_table
        self._result: list[dict] = []

    def execute(self, sql, params=None):
        table = next(t for t in self._rows_by_table if t in sql)
        rows = sorted(self._rows_by_table[table], key=lambda r: str(r["id"]))
        if "count(*)" in sql.lower():
            self._result = [{"n": len(rows)}]
            return
        if params:
            rows = rows[: params[0]]
        self._result = rows

    def fetchall(self):
        return list(self._result)

    def fetchone(self):
        return self._result[0]


@pytest.fixture
def fake_legacy(monkeypatch):
    """Патчит ``etl_media.legacy_cursor`` на фикстурные данные; возвращает
    ``rows_by_table`` для сверки в тестах."""
    rows_by_table = _rows_by_table()

    @contextlib.contextmanager
    def _fake_legacy_cursor(dsn=None):
        yield _FakeLegacyCursor(rows_by_table)

    monkeypatch.setattr(etl_media, "legacy_cursor", _fake_legacy_cursor)
    return rows_by_table


@pytest.mark.django_db
def test_sync_creates_rows_with_correct_fields(fake_legacy):
    call_command("etl_media")

    assert models.FileMetadata.objects.count() == 2
    assert models.FileVariant.objects.count() == 1
    assert models.AuditLog.objects.count() == 2

    meta1 = models.FileMetadata.objects.get(pk=FILE_ID_1)
    assert meta1.path == "avatar/2026/04/f1.jpg"
    assert meta1.owner_id == 7
    assert meta1.mime == "image/jpeg"
    assert meta1.kind == "image"
    assert meta1.scope == "avatar"
    assert meta1.sha256 == "a" * 64
    assert meta1.is_public is False
    assert meta1.created_at == T1

    meta2 = models.FileMetadata.objects.get(pk=FILE_ID_2)
    assert meta2.owner_id is None
    assert meta2.storage_backend == "s3"
    assert meta2.is_public is True
    assert meta2.deleted_at == T2

    variant = models.FileVariant.objects.get(pk=VARIANT_ID_1)
    assert variant.file_id == FILE_ID_1
    assert variant.variant == "thumb_256"
    assert variant.width == 256
    assert variant.height == 256

    audit1 = models.AuditLog.objects.get(pk=501)
    assert audit1.action == "file_uploaded"
    assert audit1.resource_id == str(FILE_ID_1)
    assert audit1.changes == {"mime": "image/jpeg", "size": 2048}

    audit2 = models.AuditLog.objects.get(pk=502)
    assert audit2.user_id is None
    assert audit2.changes is None


@pytest.mark.django_db
def test_sync_row_hash_matches_between_legacy_row_and_django_object(fake_legacy):
    """То же сравнение, которое --verify делает построчно: hash дампа
    legacy-строки должен совпасть с hash дампа созданного Django-объекта —
    ловит и пропущенные, и перепутанные местами колонки."""
    call_command("etl_media")

    for table, model, keys, _note in etl_media.TABLE_SPECS:
        for row in fake_legacy[table]:
            obj = model.objects.get(pk=row["id"])
            legacy_hash = etl_media.row_hash(etl_media._row_fields(row, keys))
            django_hash = etl_media.row_hash(etl_media._obj_fields(obj, keys))
            assert legacy_hash == django_hash, f"{table} pk={row['id']}: hash mismatch"


@pytest.mark.django_db
def test_sync_is_idempotent(fake_legacy):
    call_command("etl_media")
    call_command("etl_media")

    assert models.FileMetadata.objects.count() == 2
    assert models.FileVariant.objects.count() == 1
    assert models.AuditLog.objects.count() == 2
    # Обновление существующей записи, а не дубль с новым pk.
    assert models.AuditLog.objects.get(pk=501).action == "file_uploaded"


@pytest.mark.django_db
def test_dry_run_writes_nothing(fake_legacy):
    call_command("etl_media", "--dry-run")

    assert models.FileMetadata.objects.count() == 0
    assert models.FileVariant.objects.count() == 0
    assert models.AuditLog.objects.count() == 0


@pytest.mark.django_db
def test_verify_after_sync_passes(fake_legacy):
    call_command("etl_media")
    call_command("etl_media", "--verify")  # не должен поднять CommandError


@pytest.mark.django_db
def test_verify_raises_on_count_mismatch(fake_legacy):
    call_command("etl_media")
    models.AuditLog.objects.get(pk=502).delete()

    with pytest.raises(CommandError):
        call_command("etl_media", "--verify")


@pytest.mark.django_db
def test_verify_raises_on_hash_mismatch(fake_legacy):
    call_command("etl_media")
    meta = models.FileMetadata.objects.get(pk=FILE_ID_1)
    meta.mime = "corrupted/mismatch"
    meta.save(update_fields=["mime"])

    with pytest.raises(CommandError):
        call_command("etl_media", "--verify")
