"""Контракт apps/mail/services/sender/gmail.py — порт
services/email/app/services/sender/gmail.py. Живой HTTP замокан на seam
``_post_send``; токен-рефреш замокан на ``ensure_fresh_token`` (уже отдельно
контрактно протестирован в test_sync_token_refresh.py)."""
import datetime

import pytest

from apps.mail.models import AccountProvider, AccountType, EmailAccount, EmailMessage, OAuthToken
from apps.mail.services.crypto import crypto_service
from apps.mail.services.sender import gmail as sender_gmail


class _FakeResponse:
    def __init__(self, status_code, json_data=None, text=""):
        self.status_code = status_code
        self._json = json_data or {}
        self.text = text

    def json(self):
        return self._json


@pytest.fixture
def account(db) -> EmailAccount:
    tok = OAuthToken.objects.create(
        user_id=1, provider="google", provider_account_id="acct@example.com",
        encrypted_access_token=crypto_service.encrypt("real-access-token"),
        expires_at=datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1),
    )
    return EmailAccount.objects.create(
        user_id=1, type=AccountType.PERSONAL, provider=AccountProvider.GOOGLE,
        address="acct@example.com", display_name="Sender Name", oauth_token=tok,
    )


def _message(**kw) -> EmailMessage:
    defaults = dict(
        user_id=1, sender_email="acct@example.com", subject="Hi", body_text="hello",
        to_recipients=[{"email": "to@example.com"}],
        date=datetime.datetime.now(datetime.timezone.utc),
    )
    defaults.update(kw)
    return EmailMessage.objects.create(**defaults)


@pytest.mark.django_db
def test_gmail_sender_success_returns_provider_ids(account, monkeypatch):
    captured = {}

    def _fake_post_send(access_token, body):
        captured["access_token"] = access_token
        captured["body"] = body
        return _FakeResponse(200, {"id": "gm-1", "threadId": "th-1"})

    monkeypatch.setattr(sender_gmail, "_post_send", _fake_post_send)

    msg = _message(account=account)
    result = sender_gmail.GmailSender().send(account, msg)

    assert result.ok is True
    assert result.provider_message_id == "gm-1"
    assert result.provider_thread_id == "th-1"
    assert captured["access_token"] == "real-access-token"
    assert "raw" in captured["body"]


@pytest.mark.django_db
def test_gmail_sender_includes_thread_id_when_replying(account, monkeypatch):
    captured = {}
    monkeypatch.setattr(
        sender_gmail, "_post_send",
        lambda access_token, body: captured.update(body=body) or _FakeResponse(200, {"id": "x"}),
    )
    msg = _message(account=account, thread_id="existing-thread")
    sender_gmail.GmailSender().send(account, msg)
    assert captured["body"]["threadId"] == "existing-thread"


@pytest.mark.django_db
def test_gmail_sender_maps_http_error_to_send_result_error(account, monkeypatch):
    monkeypatch.setattr(
        sender_gmail, "_post_send",
        lambda access_token, body: _FakeResponse(403, text="forbidden"),
    )
    msg = _message(account=account)
    result = sender_gmail.GmailSender().send(account, msg)
    assert result.ok is False
    assert "403" in result.error
    assert "forbidden" in result.error
