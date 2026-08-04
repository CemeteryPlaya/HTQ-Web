"""IMAP-клиент: разбор ответов сервера без живой сети.

Подменяется единственный сетевой seam — ``ImapClient._open_connection``;
всё остальное (LIST/SELECT/STATUS/SEARCH/FETCH/STORE) отвечает фейковым
``imaplib``-совместимым объектом с ответами в том же виде, в каком их
отдаёт настоящий ``imaplib``.
"""
from __future__ import annotations

import base64

import pytest
from django.test import override_settings

from apps.mail.services import imap_client
from apps.mail.services.imap_client import (
    ImapClient,
    ImapConfig,
    ImapError,
    ImapNotConfigured,
    decode_folder,
)

RAW_EML = (
    b"From: Ivan Ivanov <i.ivanov@htq.group>\r\n"
    b"To: petr@htq.group\r\n"
    b"Subject: Test\r\n"
    b"Date: Mon, 3 Aug 2026 10:00:00 +0000\r\n"
    b"Message-ID: <abc@htq.group>\r\n"
    b"Content-Type: text/plain; charset=utf-8\r\n"
    b"\r\n"
    b"Hello\r\n"
)


def _mutf7(text: str) -> str:
    body = base64.b64encode(text.encode("utf-16-be")).decode().rstrip("=").replace("/", ",")
    return "&" + body + "-"


# ── имена папок (modified UTF-7, RFC 3501) ───────────────────────────────

@pytest.mark.parametrize("name", ["Отправленные", "Корзина", "Черновики", "Спам"])
def test_decode_folder_round_trips_cyrillic(name):
    assert decode_folder(_mutf7(name)) == name


def test_decode_folder_leaves_ascii_untouched():
    assert decode_folder("INBOX") == "INBOX"
    assert decode_folder("INBOX/Archive") == "INBOX/Archive"


def test_decode_folder_unescapes_ampersand():
    assert decode_folder("R&-D") == "R&D"


def test_decode_folder_keeps_garbage_verbatim():
    """Битую последовательность лучше показать как есть, чем уронить sync."""
    assert decode_folder("&!!!-") == "&!!!-"


# ── конфигурация ─────────────────────────────────────────────────────────

def test_config_requires_host():
    with override_settings(IMAP_HOST=""):
        assert imap_client.is_configured() is False
        with pytest.raises(ImapNotConfigured):
            ImapConfig.from_settings()


def test_config_reads_tunnel_settings():
    with override_settings(
        IMAP_HOST="mail-tunnel", IMAP_PORT=1143, IMAP_SSL=False, IMAP_STARTTLS=True,
    ):
        cfg = ImapConfig.from_settings()
    assert (cfg.host, cfg.port, cfg.use_ssl, cfg.starttls) == ("mail-tunnel", 1143, False, True)


# ── фейковое соединение ──────────────────────────────────────────────────

class _FakeIMAP4:
    def __init__(self):
        self.logged_in = None
        self.selected = None
        self.stored = []
        self.logged_out = False
        self.messages = {940: RAW_EML, 941: RAW_EML}
        self.uidvalidity = 12
        self.search_fail = False

    class error(Exception):
        pass

    def login(self, user, password):
        if password == "wrong":
            raise _FakeIMAP4.error("AUTHENTICATIONFAILED")
        self.logged_in = (user, password)
        return ("OK", [b"LOGIN completed"])

    def list(self):
        return ("OK", [
            b'(\\HasNoChildren) "/" "INBOX"',
            b'(\\HasNoChildren \\Sent) "/" "&BB4EQgQ,BEAEMAQyBDsENQQ9BD0ESwQ1-"',
            b"garbage line without structure",
        ])

    def select(self, mailbox, readonly=True):
        self.selected = (mailbox, readonly)
        return ("OK", [b"2"])

    def status(self, mailbox, what):
        return ("OK", [f'"{mailbox}" (UIDVALIDITY {self.uidvalidity} UIDNEXT 942)'.encode()])

    def uid(self, command, *args):
        if command == "SEARCH":
            if self.search_fail:
                return ("NO", [b"search unavailable"])
            return ("OK", [b" ".join(str(u).encode() for u in sorted(self.messages))])
        if command == "FETCH":
            uid = int(args[0])
            raw = self.messages.get(uid)
            if raw is None:
                return ("OK", [None])
            meta = f"{uid} (UID {uid} FLAGS (\\Seen))".encode()
            return ("OK", [(meta, raw), b")"])
        if command == "STORE":
            self.stored.append((args[0], args[1], args[2]))
            return ("OK", [b"STORE completed"])
        raise AssertionError("unexpected command " + command)

    def close(self):
        self.selected = None

    def logout(self):
        self.logged_out = True
        return ("BYE", [b"logging out"])


@pytest.fixture
def client(monkeypatch):
    fake = _FakeIMAP4()
    c = ImapClient(ImapConfig(host="mail-tunnel", port=1143, use_ssl=False))
    monkeypatch.setattr(c, "_open_connection", lambda: fake)
    # ImapError ловит imaplib.IMAP4.error — фейк поднимает свой класс,
    # поэтому подменяем и его на время теста.
    monkeypatch.setattr(imap_client.imaplib.IMAP4, "error", _FakeIMAP4.error, raising=False)
    c.fake = fake
    return c


def test_login_failure_becomes_imap_error(client):
    with pytest.raises(ImapError) as exc:
        client.login("i.ivanov@htq.group", "wrong")
    assert "AUTHENTICATIONFAILED" in str(exc.value)


def test_verify_credentials_never_raises(monkeypatch):
    monkeypatch.setattr(imap_client.imaplib.IMAP4, "error", _FakeIMAP4.error, raising=False)
    monkeypatch.setattr(ImapClient, "_open_connection", lambda self: _FakeIMAP4())
    with override_settings(IMAP_HOST="mail-tunnel", IMAP_SSL=False):
        assert imap_client.verify_credentials("a@htq.group", "ok") == (True, None)
        ok, error = imap_client.verify_credentials("a@htq.group", "wrong")
    assert ok is False and "AUTHENTICATIONFAILED" in error


def test_verify_credentials_unconfigured_reports_reason():
    with override_settings(IMAP_HOST=""):
        ok, error = imap_client.verify_credentials("a@htq.group", "x")
    assert ok is False and "IMAP_HOST" in error


def test_list_folders_decodes_and_skips_unparsable(client):
    client.login("a@htq.group", "ok")
    assert client.list_folders() == ["INBOX", "Отправленные"]


def test_select_returns_uid_cursor(client):
    client.login("a@htq.group", "ok")
    state = client.select("INBOX")
    assert state == {"uidvalidity": 12, "uidnext": 942}


def test_search_uids_filters_out_stale_tail(client):
    """`N:*` на пустом хвосте возвращает последнее письмо — оно уже
    обработано и не должно приезжать повторно."""
    client.login("a@htq.group", "ok")
    client.select("INBOX")
    assert client.search_uids(since_uid=None) == [940, 941]
    assert client.search_uids(since_uid=940) == [941]
    assert client.search_uids(since_uid=941) == []


def test_failed_search_raises_imap_error(client):
    client.login("a@htq.group", "ok")
    client.select("INBOX")
    client.fake.search_fail = True
    with pytest.raises(ImapError):
        client.search_uids()


def test_fetch_returns_raw_bytes_and_flags(client):
    client.login("a@htq.group", "ok")
    client.select("INBOX")
    msg = client.fetch(940)
    assert msg is not None
    assert msg.uid == 940
    assert msg.raw == RAW_EML
    assert msg.is_read is True
    assert msg.is_flagged is False


def test_fetch_missing_uid_returns_none(client):
    client.login("a@htq.group", "ok")
    client.select("INBOX")
    assert client.fetch(999) is None


def test_fetch_since_respects_limit(client):
    """limit берёт самые СТАРЫЕ из необработанных: курсор должен двигаться
    по порядку, иначе он перепрыгнет непрочитанные письма и они пропадут."""
    client.login("a@htq.group", "ok")
    msgs = list(client.fetch_since("INBOX", last_uid=None, limit=1))
    assert [m.uid for m in msgs] == [940]


def test_set_seen_opens_folder_writable(client):
    client.login("a@htq.group", "ok")
    assert client.set_seen("INBOX", [940, 941]) == 2
    assert client.fake.selected == ('"INBOX"', False)
    assert client.fake.stored == [("940,941", "+FLAGS", "(\\Seen)")]


def test_set_seen_noop_on_empty_list(client):
    client.login("a@htq.group", "ok")
    assert client.set_seen("INBOX", []) == 0
    assert client.fake.stored == []


def test_context_manager_logs_out(client):
    with client.login("a@htq.group", "ok"):
        pass
    assert client.fake.logged_out is True


def test_commands_before_login_fail_loudly():
    c = ImapClient(ImapConfig(host="mail-tunnel"))
    with pytest.raises(ImapError):
        c.list_folders()
