"""Контракт apps/mail/services/sender/graph.py — порт
services/email/app/services/sender/graph.py. Живой HTTP замокан на seam
``_post_send``."""
import datetime

import pytest

from apps.mail.models import AccountProvider, AccountType, EmailAccount, EmailMessage, OAuthToken
from apps.mail.services.crypto import crypto_service
from apps.mail.services.sender import graph as sender_graph


class _FakeResponse:
    def __init__(self, status_code, text=""):
        self.status_code = status_code
        self.text = text


@pytest.fixture
def account(db) -> EmailAccount:
    tok = OAuthToken.objects.create(
        user_id=1, provider="microsoft", provider_account_id="acct@example.com",
        encrypted_access_token=crypto_service.encrypt("ms-access-token"),
        expires_at=datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1),
    )
    return EmailAccount.objects.create(
        user_id=1, type=AccountType.PERSONAL, provider=AccountProvider.MICROSOFT,
        address="acct@example.com", oauth_token=tok,
    )


def _message(**kw) -> EmailMessage:
    defaults = dict(
        user_id=1, sender_email="acct@example.com", subject="Hi",
        body_html="<p>hello</p>",
        to_recipients=[{"email": "to@example.com", "name": "To"}],
        cc_recipients=[{"email": "cc@example.com"}],
        date=datetime.datetime.now(datetime.timezone.utc),
    )
    defaults.update(kw)
    return EmailMessage.objects.create(**defaults)


@pytest.mark.django_db
def test_graph_sender_builds_expected_payload_shape(account, monkeypatch):
    captured = {}

    def _fake_post_send(access_token, payload):
        captured["access_token"] = access_token
        captured["payload"] = payload
        return _FakeResponse(202)

    monkeypatch.setattr(sender_graph, "_post_send", _fake_post_send)

    msg = _message(account=account)
    result = sender_graph.GraphSender().send(account, msg)

    assert result.ok is True
    assert captured["access_token"] == "ms-access-token"
    payload = captured["payload"]["message"]
    assert payload["subject"] == "Hi"
    assert payload["body"] == {"contentType": "html", "content": "<p>hello</p>"}
    assert payload["toRecipients"] == [{"emailAddress": {"address": "to@example.com", "name": "To"}}]
    assert payload["ccRecipients"] == [{"emailAddress": {"address": "cc@example.com"}}]
    assert captured["payload"]["saveToSentItems"] is True


@pytest.mark.django_db
def test_graph_sender_uses_text_content_type_when_no_html(account, monkeypatch):
    monkeypatch.setattr(
        sender_graph, "_post_send",
        lambda access_token, payload: _FakeResponse(202),
    )
    msg = _message(account=account, body_html=None, body_text="plain body")
    # Re-fetch captured payload via a mutable closure instead:
    captured = {}
    monkeypatch.setattr(
        sender_graph, "_post_send",
        lambda access_token, payload: captured.update(payload=payload) or _FakeResponse(202),
    )
    sender_graph.GraphSender().send(account, msg)
    assert captured["payload"]["message"]["body"] == {"contentType": "text", "content": "plain body"}


@pytest.mark.django_db
def test_graph_sender_maps_http_error(account, monkeypatch):
    monkeypatch.setattr(
        sender_graph, "_post_send",
        lambda access_token, payload: _FakeResponse(401, text="unauthorized"),
    )
    msg = _message(account=account)
    result = sender_graph.GraphSender().send(account, msg)
    assert result.ok is False
    assert "401" in result.error
