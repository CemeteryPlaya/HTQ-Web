"""Слой провижининга: кто именно заводит ящик на почтовом сервере.

Живой сети нет нигде: Mailcow-ветка подменяет ``MailcowClient``,
IMAP-ветка — ``imap_client.verify_credentials`` (единственная точка, где
IMAP-ветка вообще ходит наружу).
"""
from __future__ import annotations

import pytest
from django.test import override_settings

from apps.mail.services import provisioning
from apps.mail.services.provisioning.base import (
    ProvisioningError,
    RemoteListingUnsupported,
)
from apps.mail.services.provisioning.imap import ImapProvisioner
from apps.mail.services.provisioning.mailcow import MailcowProvisioner, _bytes_to_mb
from apps.mail.services.provisioning.noop import NoopProvisioner


# ── выбор провижинера ────────────────────────────────────────────────────

def test_auto_picks_none_when_nothing_configured():
    """Обратная совместимость: пустое окружение ведёт себя как до появления
    этого слоя — наружу не ходит никто."""
    with override_settings(MAIL_PROVISIONER="auto", MAILCOW_API_URL="", MAILCOW_API_KEY="", IMAP_HOST=""):
        assert provisioning.resolve_provisioner_name() == "none"
        assert isinstance(provisioning.get_provisioner(), NoopProvisioner)


def test_auto_picks_mailcow_when_api_configured():
    with override_settings(
        MAIL_PROVISIONER="auto", MAILCOW_API_URL="https://mail.example.com/api/v1",
        MAILCOW_API_KEY="secret", IMAP_HOST="",
    ):
        assert provisioning.resolve_provisioner_name() == "mailcow"


def test_auto_picks_imap_when_only_imap_host_configured():
    with override_settings(
        MAIL_PROVISIONER="auto", MAILCOW_API_URL="", MAILCOW_API_KEY="",
        IMAP_HOST="mail-tunnel",
    ):
        assert provisioning.resolve_provisioner_name() == "imap"
        assert isinstance(provisioning.get_provisioner(), ImapProvisioner)


def test_mailcow_wins_over_imap_when_both_configured():
    """У Mailcow есть полноценный API — он строго полезнее IMAP-проверки."""
    with override_settings(
        MAIL_PROVISIONER="auto", MAILCOW_API_URL="https://mail.example.com/api/v1",
        MAILCOW_API_KEY="secret", IMAP_HOST="mail-tunnel",
    ):
        assert provisioning.resolve_provisioner_name() == "mailcow"


def test_explicit_setting_overrides_autodetection():
    with override_settings(
        MAIL_PROVISIONER="none", MAILCOW_API_URL="https://mail.example.com/api/v1",
        MAILCOW_API_KEY="secret",
    ):
        assert provisioning.resolve_provisioner_name() == "none"


def test_unknown_value_falls_back_to_auto():
    with override_settings(MAIL_PROVISIONER="carrier-pigeon", IMAP_HOST="mail-tunnel"):
        assert provisioning.resolve_provisioner_name() == "imap"


def test_describe_reports_what_ui_needs():
    with override_settings(
        MAIL_PROVISIONER="auto", MAILCOW_API_URL="", MAILCOW_API_KEY="",
        IMAP_HOST="mail-tunnel", IMAP_PORT=1143, MAILCOW_DOMAIN="htq.group",
    ):
        info = provisioning.describe()
    assert info["provisioner"] == "imap"
    assert info["domain"] == "htq.group"
    assert info["imap_host"] == "mail-tunnel"
    assert info["imap_port"] == 1143
    # Главное, что читает форма создания: сервер сам ящик НЕ заведёт.
    assert info["can_create_remotely"] is False
    assert info["can_list_remote"] is False


# ── Mailcow ──────────────────────────────────────────────────────────────

class _FakeMailcowClient:
    def __init__(self):
        self.calls = []

    def create_mailbox(self, **kw):
        self.calls.append(("create_mailbox", kw))
        return [{"type": "success"}]

    def edit_mailbox(self, address, attr):
        self.calls.append(("edit_mailbox", address, attr))
        return [{"type": "success"}]

    def set_active(self, address, *, active):
        self.calls.append(("set_active", address, active))
        return [{"type": "success"}]

    def reset_password(self, address, new_password, *, force_change=True):
        self.calls.append(("reset_password", address, new_password, force_change))
        return [{"type": "success"}]

    def delete_mailbox(self, address):
        self.calls.append(("delete_mailbox", address))
        return [{"type": "success"}]

    def list_mailboxes(self, domain=None):
        self.calls.append(("list_mailboxes", domain))
        return [
            {
                "username": "i.ivanov@htq.group", "local_part": "i.ivanov",
                "domain": "htq.group", "quota": 2 * 1024 * 1024 * 1024,
                "name": "Иван Иванов", "active": "1",
            },
        ]

    def add_app_password(self, **kw):
        self.calls.append(("add_app_password", kw))
        return [{"type": "success"}]


def test_mailcow_create_calls_api():
    client = _FakeMailcowClient()
    MailcowProvisioner(client).create(
        local_part="i.ivanov", domain="htq.group", address="i.ivanov@htq.group",
        password="S3cret!", full_name="Иван Иванов", quota_mb=2048,
    )
    action, kw = client.calls[0]
    assert action == "create_mailbox"
    assert kw["local_part"] == "i.ivanov"
    assert kw["quota_mb"] == 2048


def test_mailcow_list_remote_converts_quota_bytes_to_mb():
    """Mailcow отдаёт квоту в байтах, платформа хранит мегабайты — без
    пересчёта сверка нашла бы расхождение на каждом ящике."""
    rows = MailcowProvisioner(_FakeMailcowClient()).list_remote()
    assert len(rows) == 1
    assert rows[0].address == "i.ivanov@htq.group"
    assert rows[0].quota_mb == 2048
    assert rows[0].active is True


def test_bytes_to_mb_handles_garbage():
    assert _bytes_to_mb(None) == 0
    assert _bytes_to_mb("") == 0
    assert _bytes_to_mb(1024 * 1024) == 1


def test_mailcow_update_skips_call_when_nothing_changed():
    client = _FakeMailcowClient()
    MailcowProvisioner(client).update(address="a@htq.group")
    assert client.calls == []


def test_mailcow_error_becomes_provisioning_error():
    class _Raising(_FakeMailcowClient):
        def create_mailbox(self, **kw):
            raise RuntimeError("mailcow unreachable")

    with pytest.raises(ProvisioningError) as exc:
        MailcowProvisioner(_Raising()).create(
            local_part="a", domain="htq.group", address="a@htq.group", password="x",
        )
    assert "mailcow unreachable" in str(exc.value)


# ── IMAP (сервер без админ-API) ──────────────────────────────────────────

def test_imap_create_verifies_credentials_instead_of_creating(monkeypatch):
    """По IMAP ящик создать нельзя — можно только убедиться, что он есть."""
    seen = {}

    def _verify(username, password):
        seen["args"] = (username, password)
        return True, None

    monkeypatch.setattr(
        "apps.mail.services.provisioning.imap.imap_client.verify_credentials", _verify,
    )
    ImapProvisioner().create(
        local_part="i.ivanov", domain="htq.group",
        address="i.ivanov@htq.group", password="S3cret!",
    )
    assert seen["args"] == ("i.ivanov@htq.group", "S3cret!")


def test_imap_create_without_password_explains_why(monkeypatch):
    with pytest.raises(ProvisioningError) as exc:
        ImapProvisioner().create(
            local_part="a", domain="htq.group", address="a@htq.group", password="",
        )
    assert "не умеет создавать ящики" in str(exc.value)


def test_imap_create_failed_login_reports_server_message(monkeypatch):
    monkeypatch.setattr(
        "apps.mail.services.provisioning.imap.imap_client.verify_credentials",
        lambda u, p: (False, "AUTHENTICATIONFAILED"),
    )
    with pytest.raises(ProvisioningError) as exc:
        ImapProvisioner().create(
            local_part="a", domain="htq.group", address="a@htq.group", password="wrong",
        )
    assert "AUTHENTICATIONFAILED" in str(exc.value)


def test_imap_reset_password_verifies_new_password(monkeypatch):
    """Сменить пароль по IMAP невозможно — платформа лишь проверяет, что
    пароль, поставленный админом на сервере, действительно работает."""
    monkeypatch.setattr(
        "apps.mail.services.provisioning.imap.imap_client.verify_credentials",
        lambda u, p: (False, "no"),
    )
    with pytest.raises(ProvisioningError) as exc:
        ImapProvisioner().reset_password(address="a@htq.group", new_password="new")
    assert "Смените пароль на почтовом сервере" in str(exc.value)


def test_imap_list_remote_is_unsupported_not_broken():
    """Отсутствие списка — свойство протокола, а не сбой: сверка ловит именно
    этот тип и переключается на поштучную проверку."""
    with pytest.raises(RemoteListingUnsupported):
        ImapProvisioner().list_remote()


def test_noop_list_remote_also_unsupported():
    with pytest.raises(RemoteListingUnsupported):
        NoopProvisioner().list_remote()


def test_noop_operations_do_nothing_quietly():
    p = NoopProvisioner()
    p.create(local_part="a", domain="b", address="a@b", password="x")
    p.update(address="a@b", full_name="X")
    p.reset_password(address="a@b", new_password="x")
    p.set_active(address="a@b", active=False)
    p.delete(address="a@b")
    assert p.verify(address="a@b", password="x") == (False, "почтовый сервер не подключён")
