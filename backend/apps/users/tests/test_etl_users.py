"""Юнит-тесты ETL-команды users (фаза 10, P0.0 — целостность id-пространства).

Живого источника (auth.users) в тест-копии нет → мокаем ``legacy_cursor``
фикстурными строками. Проверяем: СОХРАНЕНИЕ id, перенос bcrypt-пароля как есть,
неперезапись auto_now-таймстемпов, сброс sequence (нет коллизии с живым create),
и hash-сверку --verify.
"""
from __future__ import annotations

import contextlib
import datetime
from io import StringIO

import pytest
from django.core.management import call_command

from apps.core.etl import row_hash
from apps.users.management.commands import etl_users as cmd
from apps.users.models import User, UserStatus

UTC = datetime.timezone.utc

# Один legacy-пользователь с ЯВНЫМ id=500 и bcrypt-хэшем (FastAPI-период).
_BCRYPT = "$2b$12$abcdefghijklmnopqrstuvABCDEFGHIJKLMNOPQRSTUVWXYZ012345"
_ROW = {
    "id": 500,
    "username": "legacy.user",
    "email": "legacy@example.com",
    "password_hash": _BCRYPT,
    "first_name": "Иван", "last_name": "Петров", "patronymic": "Сергеевич",
    "display_name": "И. Петров", "bio": "", "phone": "+70000000000",
    "avatar_url": "avatars/500.png",
    "settings": {"theme": "dark"},
    "status": UserStatus.ACTIVE,
    "is_staff": True, "is_superuser": False, "must_change_password": False,
    "date_joined": datetime.datetime(2025, 1, 1, tzinfo=UTC),
    "last_login": datetime.datetime(2026, 6, 1, tzinfo=UTC),
    "created_at": datetime.datetime(2025, 1, 1, tzinfo=UTC),
    "updated_at": datetime.datetime(2026, 6, 2, tzinfo=UTC),
}


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows
        self._last = None

    def execute(self, sql, params=None):
        self._last = sql

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        # verify считает count(*) → {"n": N}
        return {"n": len(self._rows)}


def _patch_source(monkeypatch, rows):
    @contextlib.contextmanager
    def fake_legacy_cursor(dsn=None):
        yield _FakeCursor(rows)
    monkeypatch.setattr(cmd, "legacy_cursor", fake_legacy_cursor)


def test_utc_normalizes():
    naive = datetime.datetime(2025, 1, 1, 12, 0, 0)
    assert cmd._utc(naive) == naive.replace(tzinfo=UTC)
    assert cmd._utc(None) is None


@pytest.mark.django_db
def test_load_preserves_id_password_and_timestamps(monkeypatch):
    _patch_source(monkeypatch, [_ROW])
    call_command("etl_users", stdout=StringIO())

    u = User.objects.get(id=500)                 # id СОХРАНЁН (критично для user_id доменов)
    assert u.username == "legacy.user"
    assert u.password == _BCRYPT                  # bcrypt перенесён как есть (не перехэширован)
    assert u.first_name == "Иван" and u.patronymic == "Сергеевич"
    assert u.settings == {"theme": "dark"}
    assert u.status == UserStatus.ACTIVE and u.is_staff is True
    # auto_now(_add) НЕ затёрли legacy-таймстемпы
    assert cmd._utc(u.date_joined) == _ROW["date_joined"]
    assert cmd._utc(u.created_at) == _ROW["created_at"]
    assert cmd._utc(u.updated_at) == _ROW["updated_at"]


@pytest.mark.django_db
def test_bcrypt_password_still_authenticates(monkeypatch):
    # хэш от "secret123" — проверяем, что перенесённый bcrypt принимается check_password
    import bcrypt as bcrypt_lib
    h = bcrypt_lib.hashpw(b"secret123", bcrypt_lib.gensalt()).decode()
    row = {**_ROW, "id": 501, "username": "u501", "email": "u501@example.com", "password_hash": h}
    _patch_source(monkeypatch, [row])
    call_command("etl_users", stdout=StringIO())
    assert User.objects.get(id=501).check_password("secret123") is True


@pytest.mark.django_db
def test_sequence_reset_prevents_collision(monkeypatch):
    _patch_source(monkeypatch, [_ROW])                     # вставит id=500
    call_command("etl_users", stdout=StringIO())
    # живое создание ПОСЛЕ ETL не должно столкнуться с занятым id=500
    fresh = User.objects.create(username="after-etl", email="after@example.com",
                                password="x", status=UserStatus.ACTIVE)
    assert fresh.id > 500


@pytest.mark.django_db
def test_dry_run_writes_nothing(monkeypatch):
    _patch_source(monkeypatch, [_ROW])
    call_command("etl_users", "--dry-run", stdout=StringIO())
    assert not User.objects.filter(id=500).exists()


@pytest.mark.django_db
def test_verify_hash_matches_after_load(monkeypatch):
    _patch_source(monkeypatch, [_ROW])
    call_command("etl_users", stdout=StringIO())
    out = StringIO()
    call_command("etl_users", "--verify", stdout=out)
    rendered = out.getvalue()
    assert "users_user" in rendered
    assert "ЗЕЛЁНЫЙ" in rendered
    # та же форма сверки, что команда: row_hash(source) == row_hash(obj)
    u = User.objects.get(id=500)
    assert row_hash(cmd._to_user_fields(_ROW)) == row_hash(cmd._obj_fields(u))
