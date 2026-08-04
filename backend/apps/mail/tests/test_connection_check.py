"""Проверка связи с почтовым сервером (``services/connection_check.py``).

Этой логикой пользуются двое — ``manage.py mail_check`` и кнопка «Проверить»
в интерфейсе, — поэтому поведение проверяется здесь, у самого сервиса, а не
в тестах одного из потребителей.

Живой сети нет: подменяются ``socket.create_connection``, IMAP-соединение и
``smtplib.SMTP``.
"""
from __future__ import annotations

import smtplib

import pytest
from django.test import override_settings

from apps.mail.services import connection_check
from apps.mail.services import imap_client as imap_module

SECRET = "SuperSecret!42"

TUNNEL_SETTINGS = dict(
    MAILCOW_DOMAIN="htq.group",
    MAIL_PROVISIONER="imap",
    IMAP_HOST="mail-tunnel", IMAP_PORT=1143, IMAP_SSL=False, IMAP_STARTTLS=False,
    SMTP_HOST="mail-tunnel", SMTP_PORT=1587, SMTP_SSL=False, SMTP_STARTTLS=False,
    MAIL_SYNC_FOLDERS=["INBOX", "Sent"],
)


def _step(report, key):
    for step in report.steps:
        if step.key == key:
            return step
    return None


def _statuses(report) -> dict[str, str]:
    return {s.key: s.status for s in report.steps}


# ── фикстуры ─────────────────────────────────────────────────────────────

@pytest.fixture
def unreachable(monkeypatch):
    """Порты закрыты — типовая картина, когда туннель не поднят."""
    def _boom(*a, **kw):
        raise OSError("[Errno 111] Connection refused")
    monkeypatch.setattr(connection_check.socket, "create_connection", _boom)


@pytest.fixture
def reachable(monkeypatch):
    class _Sock:
        def __enter__(self): return self
        def __exit__(self, *a): return None
    monkeypatch.setattr(
        connection_check.socket, "create_connection", lambda *a, **kw: _Sock(),
    )


class _FakeIMAP4:
    class error(Exception):
        pass

    def __init__(self, folders=("INBOX", "Sent"), bad_password="wrong"):
        self._folders = folders
        self._bad_password = bad_password

    def login(self, user, password):
        if password == self._bad_password:
            raise _FakeIMAP4.error("AUTHENTICATIONFAILED")
        return ("OK", [b"LOGIN completed"])

    def list(self):
        return ("OK", [f'(\\HasNoChildren) "/" "{f}"'.encode() for f in self._folders])

    def select(self, mailbox, readonly=True):
        return ("OK", [b"1"])

    def status(self, mailbox, what):
        return ("OK", [f"{mailbox} (UIDVALIDITY 12 UIDNEXT 5)".encode()])

    def uid(self, command, *args):
        return ("OK", [b"1 2 3"])

    def close(self):
        return None

    def logout(self):
        return ("BYE", [b"bye"])


@pytest.fixture
def fake_imap(monkeypatch):
    def _install(**kw):
        fake = _FakeIMAP4(**kw)
        monkeypatch.setattr(imap_module.ImapClient, "_open_connection", lambda self: fake)
        monkeypatch.setattr(imap_module.imaplib.IMAP4, "error", _FakeIMAP4.error, raising=False)
        return fake
    return _install


class _FakeSMTP:
    instances: list["_FakeSMTP"] = []

    def __init__(self, host, port, timeout=None):
        self.host, self.port = host, port
        self.logged_in = None
        self.sent = []
        _FakeSMTP.instances.append(self)

    def __enter__(self): return self

    def __exit__(self, *a): return None

    def ehlo(self): return (250, b"ok")

    def starttls(self, *a, **kw): return (220, b"ready")

    def login(self, user, password):
        if password == "wrong":
            raise smtplib.SMTPAuthenticationError(535, b"auth failed")
        self.logged_in = user

    def send_message(self, message):
        self.sent.append(message)


@pytest.fixture
def fake_smtp(monkeypatch):
    _FakeSMTP.instances = []
    monkeypatch.setattr(connection_check.smtplib, "SMTP", _FakeSMTP)
    return _FakeSMTP


# ── настройки ────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_missing_domain_is_a_failure(unreachable):
    with override_settings(MAILCOW_DOMAIN="", MAIL_PROVISIONER="none", IMAP_HOST="", SMTP_HOST=""):
        report = connection_check.run_check(timeout=1)

    assert not report.ok
    config = _step(report, "config")
    assert config.status == connection_check.FAIL
    assert "Домен ящиков не задан" in config.detail
    assert config.hint  # подсказка обязана быть, а не голая констатация


@pytest.mark.django_db
def test_unconnected_server_is_a_failure(unreachable):
    """Домен задан, но сервера нет: ящики осели бы только в базе платформы."""
    with override_settings(
        MAILCOW_DOMAIN="htq.group", MAIL_PROVISIONER="none", IMAP_HOST="", SMTP_HOST="",
    ):
        report = connection_check.run_check(timeout=1)

    assert not report.ok
    assert "не подключён" in _step(report, "config").detail


@pytest.mark.django_db
def test_configured_server_passes_the_config_step(unreachable):
    with override_settings(**TUNNEL_SETTINGS):
        report = connection_check.run_check(timeout=1)

    config = _step(report, "config")
    assert config.status == connection_check.OK
    assert "imap" in config.detail and "htq.group" in config.detail


# ── порты ────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_closed_port_points_at_the_tunnel(unreachable):
    with override_settings(**TUNNEL_SETTINGS):
        report = connection_check.run_check(timeout=1)

    assert not report.ok
    port = _step(report, "imap_port")
    assert port.status == connection_check.FAIL
    assert "mail-tunnel:1143" in port.detail
    assert "--profile mail-tunnel up -d mail-tunnel" in port.hint


@pytest.mark.django_db
def test_protocol_checks_are_skipped_when_port_is_closed(unreachable):
    """Иначе поверх одной настоящей причины сыпались бы производные ошибки."""
    with override_settings(**TUNNEL_SETTINGS):
        report = connection_check.run_check(timeout=1)

    statuses = _statuses(report)
    assert statuses["imap"] == connection_check.SKIP
    assert statuses["smtp"] == connection_check.SKIP


# ── IMAP ─────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_connection_alone_needs_no_credentials(reachable, fake_imap, fake_smtp):
    """Отладить туннель можно, не зная ни одного пароля."""
    fake_imap()
    with override_settings(**TUNNEL_SETTINGS):
        report = connection_check.run_check(timeout=1)

    assert report.ok
    assert _step(report, "imap").status == connection_check.OK
    assert _step(report, "imap_login").status == connection_check.SKIP


@pytest.mark.django_db
def test_successful_login_reports_folders_and_counts(reachable, fake_imap, fake_smtp):
    fake_imap()
    with override_settings(**TUNNEL_SETTINGS):
        report = connection_check.run_check(
            mailbox="i.ivanov@htq.group", password=SECRET, timeout=1,
        )

    assert report.ok
    assert _step(report, "imap_login").status == connection_check.OK
    folders = _step(report, "folders")
    assert folders.status == connection_check.OK
    assert folders.data["counts"]["INBOX"]["messages"] == 3
    assert folders.data["counts"]["INBOX"]["uidvalidity"] == 12


@pytest.mark.django_db
def test_missing_sync_folder_lists_the_real_names(reachable, fake_imap, fake_smtp):
    """Самая частая настроечная ошибка: папка называется «Sent Items» или
    «Отправленные», а в настройках стоит «Sent»."""
    fake_imap(folders=("INBOX", "Sent Items"))
    with override_settings(**TUNNEL_SETTINGS):
        report = connection_check.run_check(
            mailbox="i.ivanov@htq.group", password=SECRET, timeout=1,
        )

    assert not report.ok
    folders = _step(report, "folders")
    assert "Sent" in folders.detail
    assert "Sent Items" in folders.data["available"]
    assert folders.hint


@pytest.mark.django_db
def test_bad_credentials_do_not_echo_the_password(reachable, fake_imap, fake_smtp):
    fake_imap()
    with override_settings(**TUNNEL_SETTINGS):
        report = connection_check.run_check(
            mailbox="i.ivanov@htq.group", password="wrong", timeout=1,
        )

    assert not report.ok
    assert _step(report, "imap_login").status == connection_check.FAIL
    assert "wrong" not in str(report.to_dict())


@pytest.mark.django_db
def test_password_never_reaches_the_report(reachable, fake_imap, fake_smtp):
    """Отчёт уезжает в браузер и в тикеты — секрет туда попасть не должен."""
    fake_imap()
    with override_settings(**TUNNEL_SETTINGS):
        report = connection_check.run_check(
            mailbox="i.ivanov@htq.group", password=SECRET, timeout=1,
        )

    assert SECRET not in str(report.to_dict())


@pytest.mark.django_db
def test_mailbox_without_password_explains_what_to_do(reachable, fake_imap, fake_smtp):
    fake_imap()
    with override_settings(**TUNNEL_SETTINGS):
        report = connection_check.run_check(mailbox="nobody@htq.group", timeout=1)

    login = _step(report, "imap_login")
    assert login.status == connection_check.FAIL
    assert "nobody@htq.group" in login.detail
    assert login.hint


# ── SMTP ─────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_smtp_login_is_checked_too(reachable, fake_imap, fake_smtp):
    fake_imap()
    with override_settings(**TUNNEL_SETTINGS):
        report = connection_check.run_check(
            mailbox="i.ivanov@htq.group", password=SECRET, timeout=1,
        )

    assert _step(report, "smtp_login").status == connection_check.OK
    assert fake_smtp.instances[-1].logged_in == "i.ivanov@htq.group"


@pytest.mark.django_db
def test_probe_email_only_on_explicit_request(reachable, fake_imap, fake_smtp):
    """send_to шлёт НАСТОЯЩЕЕ письмо, поэтому по умолчанию не срабатывает."""
    fake_imap()
    with override_settings(**TUNNEL_SETTINGS):
        report = connection_check.run_check(
            mailbox="i.ivanov@htq.group", password=SECRET, timeout=1,
        )

    assert _step(report, "probe").status == connection_check.SKIP
    assert all(not smtp.sent for smtp in fake_smtp.instances)


@pytest.mark.django_db
def test_probe_email_is_sent_from_the_mailbox(reachable, fake_imap, fake_smtp):
    fake_imap()
    with override_settings(**TUNNEL_SETTINGS):
        report = connection_check.run_check(
            mailbox="i.ivanov@htq.group", password=SECRET,
            send_to="boss@example.com", timeout=1,
        )

    assert report.ok
    assert _step(report, "probe").status == connection_check.OK
    sent = [m for smtp in fake_smtp.instances for m in smtp.sent]
    assert len(sent) == 1
    assert sent[0]["From"] == "i.ivanov@htq.group"
    assert sent[0]["To"] == "boss@example.com"
