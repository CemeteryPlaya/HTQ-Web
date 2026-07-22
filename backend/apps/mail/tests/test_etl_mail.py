"""Юнит-тесты ``manage.py etl_mail`` (Фаза 10 — см. ``etl-contract.md`` /
``etl-mail-brief.md``, не в дереве репозитория).

Изолированно, без живой legacy-БД: ``legacy_cursor`` мокается фикстурными
dict-строками (форма ``psycopg.rows.dict_row`` — как реальный курсор
``apps/core/etl.py::legacy_cursor`` отдал бы построчно). Прогонять ТОЛЬКО
этот файл:
``.venv/Scripts/python.exe -m pytest apps/mail/tests/test_etl_mail.py -q``.

Два слоя:
  * "чистый" маппинг (``_oauth_row``/``_oauth_obj``, ``_msg_row``/``_msg_obj``)
    — реальный Django-объект создаётся напрямую (без прогона команды),
    сверяется ``row_hash`` источник vs цель (та же форма, что ``--verify``
    использует в проде).
  * команда целиком (``call_command("etl_mail", ...)``) с фиктивным
    ``legacy_cursor`` — загрузка+идемпотентность, ``--dry-run`` ничего не
    пишет, ``--verify`` даёт зелёный отчёт на полных данных и падает
    (``CommandError``, код выхода 1 в реальном CLI) при намеренном
    расхождении count.
"""
from __future__ import annotations

import contextlib
import datetime
import io
import re
import uuid

import pytest
from django.core.management import CommandError, call_command

from apps.core.etl import row_hash
from apps.mail.management.commands import etl_mail
from apps.mail.models import EmailAccount, EmailMessage, OAuthToken

UTC = datetime.timezone.utc


# ── фиктурные legacy-строки (форма dict_row) ────────────────────────────────

OAUTH_TOKEN_ROWS = [
    {
        "id": 1,
        "user_id": 101,
        "provider": "google",
        "provider_account_id": "user1@example.com",
        "encrypted_access_token": "enc-access-1",
        "encrypted_refresh_token": "enc-refresh-1",
        "expires_at": datetime.datetime(2026, 3, 1, tzinfo=UTC),
        "is_active": True,
        "created_at": datetime.datetime(2026, 1, 1, tzinfo=UTC),
        "updated_at": datetime.datetime(2026, 1, 2, tzinfo=UTC),
    },
    {
        "id": 2,
        "user_id": 102,
        "provider": "microsoft",
        "provider_account_id": "user2@example.com",
        "encrypted_access_token": "enc-access-2",
        "encrypted_refresh_token": None,
        "expires_at": datetime.datetime(2026, 3, 2, tzinfo=UTC),
        "is_active": False,
        "created_at": datetime.datetime(2026, 1, 3, tzinfo=UTC),
        "updated_at": datetime.datetime(2026, 1, 4, tzinfo=UTC),
    },
]

EMAIL_ACCOUNT_ROWS = [
    {
        "id": 1,
        "user_id": 101,
        "type": "personal",
        "provider": "google",
        "address": "user1@example.com",
        "display_name": "User One",
        "is_default": True,
        "is_active": True,
        "mailbox_id": None,
        "oauth_token_id": 1,
        "sync_state": {"history_id": "abc"},
        "last_sync_at": datetime.datetime(2026, 1, 5, tzinfo=UTC),
        "last_sync_error": None,
        "watch_expires_at": None,
        "connected_at": datetime.datetime(2026, 1, 1, tzinfo=UTC),
        "created_at": datetime.datetime(2026, 1, 1, tzinfo=UTC),
        "updated_at": datetime.datetime(2026, 1, 5, tzinfo=UTC),
    },
]

FIXTURES = {
    "oauth_tokens": OAUTH_TOKEN_ROWS,
    "email_accounts": EMAIL_ACCOUNT_ROWS,
    # остальные 5 legacy-таблиц домена (provisioned_mailboxes/email_messages/
    # email_attachments/recipient_statuses/audit_log) намеренно без фикстур —
    # _FakeCursor отдаёт под них [] (0 строк), SPECS-цикл проходит их без
    # ошибок, отчёт --verify считает src=tgt=0 честным OK.
}


class _FakeCursor:
    """Мини dict-row курсор поверх фикстур — отвечает на 3 формы SQL, которые
    реально шлёт etl_mail.py:

      1. ``_table_exists``: ``SELECT EXISTS (... information_schema.tables
         WHERE table_schema = %s AND table_name = %s) AS present`` — имя
         таблицы приходит ВТОРЫМ параметром (не текстом в SQL).
      2. ``legacy_count``: ``SELECT count(*) AS n FROM "email"."<table>"``.
      3. ``_fetch_rows``: ``SELECT * FROM "email"."<table>" ORDER BY "id"
         [LIMIT %s]`` — имя таблицы парсится из текста SQL.

    ``missing_tables`` симулирует реально обнаруженный при боевом прогоне
    случай — ``email.audit_log`` физически отсутствует в копии БД (см.
    ``etl_mail.py`` module docstring) — команда должна пережить это, не упасть.
    """

    _TABLE_RE = re.compile(r'"email"\."(\w+)"')

    def __init__(self, fixtures: dict[str, list[dict]], missing_tables: frozenset[str] = frozenset()):
        self._fixtures = fixtures
        self._missing_tables = missing_tables
        self._count = 0
        self._rows: list[dict] = []
        self._exists = True

    def execute(self, sql, params=None):
        upper = sql.strip().upper()
        if "INFORMATION_SCHEMA.TABLES" in upper:
            table = params[1] if params else None
            self._exists = table not in self._missing_tables
            return

        m = self._TABLE_RE.search(sql)
        table = m.group(1) if m else None
        rows = list(self._fixtures.get(table, []))
        if upper.startswith("SELECT COUNT"):
            self._count = len(rows)
            self._rows = []
        else:
            rows.sort(key=lambda r: r["id"])
            if params:
                rows = rows[: params[0]]
            self._rows = rows

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return {"n": self._count, "present": self._exists}


def _make_legacy_cursor(fixtures: dict[str, list[dict]], missing_tables: frozenset[str] = frozenset()):
    @contextlib.contextmanager
    def _cursor(dsn=None):
        yield _FakeCursor(fixtures, missing_tables)
    return _cursor


# ── маппинг: row_hash(source) == row_hash(target) на реальном Django-объекте ─

@pytest.mark.django_db
def test_oauth_token_mapping_row_hash_matches_after_create():
    row = OAUTH_TOKEN_ROWS[0]
    OAuthToken.objects.create(id=row["id"], **etl_mail._oauth_row(row))
    obj = OAuthToken.objects.get(pk=row["id"])

    assert row_hash(etl_mail._oauth_row(row)) == row_hash(etl_mail._oauth_obj(obj))
    # шифртекст переносится байт-в-байт, без транформаций
    assert obj.encrypted_access_token == "enc-access-1"
    assert obj.encrypted_refresh_token == "enc-refresh-1"


@pytest.mark.django_db
def test_email_message_mapping_row_hash_matches_after_create():
    msg_id = uuid.uuid4()
    row = {
        "id": msg_id,
        "user_id": 7,
        "account_id": None,
        "message_id": "ext-123",
        "thread_id": "thread-1",
        "folder": "inbox",
        "provider_folder": "INBOX",
        "subject": "Hello",
        "snippet": "Hi there",
        "body_html": None,
        "body_text": "Hi there",
        "sender_email": "a@example.com",
        "sender_name": "A",
        "to_recipients": [{"email": "b@example.com", "name": "B"}],
        "cc_recipients": [],
        "bcc_recipients": [],
        "is_read": False,
        "is_flagged": True,
        "has_attachments": False,
        "date": datetime.datetime(2026, 2, 1, tzinfo=UTC),
        "dlp_flagged": False,
        "created_at": datetime.datetime(2026, 2, 1, tzinfo=UTC),
        "updated_at": datetime.datetime(2026, 2, 1, tzinfo=UTC),
    }
    EmailMessage.objects.create(id=row["id"], **etl_mail._msg_row(row))
    obj = EmailMessage.objects.get(pk=msg_id)

    assert row_hash(etl_mail._msg_row(row)) == row_hash(etl_mail._msg_obj(obj))
    assert obj.to_recipients == [{"email": "b@example.com", "name": "B"}]


# ── команда целиком (legacy_cursor замокан) ─────────────────────────────────

@pytest.mark.django_db
def test_command_load_creates_expected_rows_and_is_idempotent(monkeypatch):
    monkeypatch.setattr(etl_mail, "legacy_cursor", _make_legacy_cursor(FIXTURES))

    call_command("etl_mail", stdout=io.StringIO())
    assert OAuthToken.objects.count() == 2
    assert EmailAccount.objects.count() == 1

    tok = OAuthToken.objects.get(pk=1)
    assert tok.encrypted_access_token == "enc-access-1"
    acct = EmailAccount.objects.get(pk=1)
    assert acct.oauth_token_id == 1
    assert acct.sync_state == {"history_id": "abc"}

    # второй прогон — идемпотентно (update_or_create по натуральному id),
    # без дублей и без падений.
    call_command("etl_mail", stdout=io.StringIO())
    assert OAuthToken.objects.count() == 2
    assert EmailAccount.objects.count() == 1


@pytest.mark.django_db
def test_command_dry_run_writes_nothing(monkeypatch):
    monkeypatch.setattr(etl_mail, "legacy_cursor", _make_legacy_cursor(FIXTURES))

    call_command("etl_mail", dry_run=True, stdout=io.StringIO())

    assert OAuthToken.objects.count() == 0
    assert EmailAccount.objects.count() == 0


@pytest.mark.django_db
def test_command_verify_reports_ok_after_full_load(monkeypatch):
    monkeypatch.setattr(etl_mail, "legacy_cursor", _make_legacy_cursor(FIXTURES))
    call_command("etl_mail", stdout=io.StringIO())

    out = io.StringIO()
    call_command("etl_mail", verify=True, stdout=out)  # не должно бросить CommandError

    rendered = out.getvalue()
    assert "ЗЕЛЁНЫЙ" in rendered
    assert "email.oauth_tokens" in rendered


@pytest.mark.django_db
def test_command_verify_raises_on_count_mismatch(monkeypatch):
    monkeypatch.setattr(etl_mail, "legacy_cursor", _make_legacy_cursor(FIXTURES))
    # --limit 1 -> только первая (id=1) из двух oauth_tokens загружена
    # намеренно неполно, чтобы получить расхождение count в --verify.
    call_command("etl_mail", limit=1, stdout=io.StringIO())
    assert OAuthToken.objects.count() == 1

    out = io.StringIO()
    with pytest.raises(CommandError):
        call_command("etl_mail", verify=True, stdout=out)
    assert "DIFF" in out.getvalue()
    assert "ЕСТЬ РАСХОЖДЕНИЯ" in out.getvalue()


@pytest.mark.django_db
def test_command_handles_missing_legacy_table_gracefully(monkeypatch):
    """Реальный прогон против копии БД обнаружил, что ``email.audit_log``
    физически отсутствует (см. ``etl_mail.py`` module docstring) — ``_table_
    exists`` должен это перехватить: не падать, 0 строк, явная note (не
    молчаливое "0 строк в пустой таблице")."""
    cursor_factory = _make_legacy_cursor(FIXTURES, missing_tables=frozenset({"audit_log"}))
    monkeypatch.setattr(etl_mail, "legacy_cursor", cursor_factory)

    load_out = io.StringIO()
    call_command("etl_mail", stdout=load_out)
    assert "email.audit_log" in load_out.getvalue()
    assert "отсутствует" in load_out.getvalue()

    verify_out = io.StringIO()
    call_command("etl_mail", verify=True, stdout=verify_out)  # не должно бросить CommandError
    rendered = verify_out.getvalue()
    assert "ЗЕЛЁНЫЙ" in rendered
    assert "отсутствует" in rendered
