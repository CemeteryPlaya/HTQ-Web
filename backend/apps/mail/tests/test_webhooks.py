"""Contract tests for ``/api/email/v1/webhooks/{gmail,microsoft,mailcow}`` —
port of ``services/email/app/api/v1/webhooks.py`` (3 endpoints,
webhooks+workers sub-task, PLAN.md §6.4).

No live provider is reachable from tests (no real Google/Microsoft/Mailcow) —
coverage is against RECORDED payload shapes (Gmail Pub/Sub envelope,
Microsoft Graph notification/validation handshake) with the enqueue side
verified by monkeypatching ``incremental_sync_account.delay`` (Celery is
eager in tests — see ``htqweb/settings/test.py`` — so leaving it un-patched
would actually run the sync seam inline; patching keeps these tests focused
on the webhook contract, not the task body, which has its own suite in
``test_tasks.py``).
"""
from __future__ import annotations

import base64
import datetime
import json

import pytest
from django.test import Client, override_settings

from apps.mail.models import (
    AccountProvider,
    AccountType,
    EmailAccount,
    OAuthToken,
    ProvisionedMailbox,
)

BASE = "/api/email/v1/webhooks"


def _account(*, provider, address, **kw) -> EmailAccount:
    """Personal (OAuth) account — ``ck_email_accounts_type_consistency``
    requires a non-null ``oauth_token_id`` for ``type=PERSONAL``, so every
    caller gets one attached unless it overrides ``oauth_token``."""
    token = OAuthToken.objects.create(
        user_id=1, provider=str(provider), provider_account_id=address,
        encrypted_access_token="enc", expires_at=datetime.datetime.now(datetime.timezone.utc),
    )
    defaults = dict(
        user_id=1, type=AccountType.PERSONAL, address=address, provider=provider,
        oauth_token=token,
    )
    defaults.update(kw)
    return EmailAccount.objects.create(**defaults)


def _post_json(client, path, body, **extra):
    return client.post(path, data=json.dumps(body), content_type="application/json", **extra)


@pytest.fixture(autouse=True)
def _patch_sync_delay(monkeypatch):
    calls = []
    import apps.mail.webhooks as webhooks_mod
    monkeypatch.setattr(
        webhooks_mod.incremental_sync_account, "delay",
        lambda *a, **kw: calls.append((a, kw)),
    )
    return calls


# ── /webhooks/gmail ─────────────────────────────────────────────────────


def _gmail_envelope(*, email_address="acct@example.com", history_id="123") -> dict:
    payload = {"emailAddress": email_address, "historyId": history_id}
    data = base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")
    return {"message": {"data": data, "messageId": "m1"}, "subscription": "projects/x/subscriptions/y"}


@pytest.mark.django_db
@override_settings(GOOGLE_PUBSUB_VERIFICATION_TOKEN="")
def test_gmail_push_401_when_no_auth_configured(_patch_sync_delay):
    resp = _post_json(Client(), f"{BASE}/gmail", _gmail_envelope())
    assert resp.status_code == 401
    assert resp.json()["detail"] == "No auth configured"
    assert _patch_sync_delay == []


@pytest.mark.django_db
@override_settings(GOOGLE_PUBSUB_VERIFICATION_TOKEN="secret-tok")
def test_gmail_push_401_when_query_token_wrong(_patch_sync_delay):
    resp = _post_json(Client(), f"{BASE}/gmail?token=wrong", _gmail_envelope())
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid verification token"


@pytest.mark.django_db
@override_settings(GOOGLE_PUBSUB_VERIFICATION_TOKEN="secret-tok")
def test_gmail_push_204_and_enqueues_sync_when_account_known(_patch_sync_delay):
    acc = _account(provider=AccountProvider.GOOGLE, address="acct@example.com")
    resp = _post_json(
        Client(), f"{BASE}/gmail?token=secret-tok",
        _gmail_envelope(email_address="acct@example.com", history_id="99"),
    )
    assert resp.status_code == 204
    assert resp.content == b""
    assert len(_patch_sync_delay) == 1
    args, kwargs = _patch_sync_delay[0]
    assert args == (acc.id,)
    assert kwargs == {"hint_history_id": "99"}


@pytest.mark.django_db
@override_settings(GOOGLE_PUBSUB_VERIFICATION_TOKEN="secret-tok")
def test_gmail_push_204_when_account_unknown(_patch_sync_delay):
    resp = _post_json(
        Client(), f"{BASE}/gmail?token=secret-tok",
        _gmail_envelope(email_address="nobody@example.com"),
    )
    assert resp.status_code == 204
    assert _patch_sync_delay == []


@pytest.mark.django_db
@override_settings(GOOGLE_PUBSUB_VERIFICATION_TOKEN="secret-tok")
def test_gmail_push_204_when_envelope_has_no_message_data(_patch_sync_delay):
    resp = _post_json(Client(), f"{BASE}/gmail?token=secret-tok", {"subscription": "x"})
    assert resp.status_code == 204
    assert _patch_sync_delay == []


@pytest.mark.django_db
@override_settings(GOOGLE_PUBSUB_VERIFICATION_TOKEN="secret-tok")
def test_gmail_push_204_when_base64_payload_is_malformed(_patch_sync_delay):
    resp = _post_json(
        Client(), f"{BASE}/gmail?token=secret-tok",
        {"message": {"data": "not-valid-base64!!"}},
    )
    assert resp.status_code == 204
    assert _patch_sync_delay == []


@pytest.mark.django_db
def test_gmail_push_bearer_jwt_invalid_returns_401(_patch_sync_delay, monkeypatch):
    # No live Google service account reachable from tests ("Живой прогон
    # невозможен") — monkeypatch the one seam that would otherwise make a
    # real network call (id_token.verify_oauth2_token fetches Google's
    # public certs over HTTPS) to raise, and assert the source's own
    # exception-to-401 mapping ("Invalid Pub/Sub JWT: {exc}").
    from google.oauth2 import id_token as id_token_mod

    def _boom(token, request):
        raise ValueError("Token used too early")

    monkeypatch.setattr(id_token_mod, "verify_oauth2_token", _boom)

    resp = _post_json(
        Client(), f"{BASE}/gmail", _gmail_envelope(),
        HTTP_AUTHORIZATION="Bearer not-a-real-jwt",
    )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid Pub/Sub JWT: Token used too early"
    assert _patch_sync_delay == []


@pytest.mark.django_db
@override_settings(GOOGLE_PUBSUB_VERIFICATION_TOKEN="secret-tok")
def test_gmail_push_bearer_jwt_valid_bypasses_query_token(_patch_sync_delay, monkeypatch):
    """A verified Bearer JWT is sufficient — the query ``?token=`` fallback
    is never consulted (source: ``if authorization: ... elif settings...``,
    mutually exclusive branches)."""
    acc = _account(provider=AccountProvider.GOOGLE, address="acct@example.com")

    from google.oauth2 import id_token as id_token_mod
    monkeypatch.setattr(id_token_mod, "verify_oauth2_token", lambda token, request: {"email": "pubsub@x.iam.gserviceaccount.com"})

    resp = _post_json(
        Client(), f"{BASE}/gmail", _gmail_envelope(email_address="acct@example.com"),
        HTTP_AUTHORIZATION="Bearer a-valid-looking-jwt",
    )
    assert resp.status_code == 204
    assert len(_patch_sync_delay) == 1
    assert _patch_sync_delay[0][0] == (acc.id,)


@pytest.mark.django_db
def test_gmail_push_get_not_allowed():
    resp = Client().get(f"{BASE}/gmail")
    assert resp.status_code == 405


# ── /webhooks/microsoft ──────────────────────────────────────────────────


@pytest.mark.django_db
def test_microsoft_push_echoes_validation_token_as_plain_text():
    resp = Client().post(f"{BASE}/microsoft?validationToken=abc123")
    assert resp.status_code == 200
    assert resp.content == b"abc123"
    assert resp["Content-Type"].startswith("text/plain")


@pytest.mark.django_db
@override_settings(MICROSOFT_WEBHOOK_CLIENT_STATE="expected-state")
def test_microsoft_push_202_and_enqueues_sync_for_matching_subscription(_patch_sync_delay):
    acc = _account(
        provider=AccountProvider.MICROSOFT, address="ms@example.com",
        sync_state={"subscription_id": "sub-1"},
    )
    resp = _post_json(Client(), f"{BASE}/microsoft", {
        "value": [{"subscriptionId": "sub-1", "clientState": "expected-state"}],
    })
    assert resp.status_code == 202
    assert len(_patch_sync_delay) == 1
    assert _patch_sync_delay[0][0] == (acc.id,)


@pytest.mark.django_db
@override_settings(MICROSOFT_WEBHOOK_CLIENT_STATE="expected-state")
def test_microsoft_push_skips_notification_with_bad_client_state(_patch_sync_delay):
    _account(
        provider=AccountProvider.MICROSOFT, address="ms2@example.com",
        sync_state={"subscription_id": "sub-2"},
    )
    resp = _post_json(Client(), f"{BASE}/microsoft", {
        "value": [{"subscriptionId": "sub-2", "clientState": "wrong"}],
    })
    assert resp.status_code == 202
    assert _patch_sync_delay == []


@pytest.mark.django_db
@override_settings(MICROSOFT_WEBHOOK_CLIENT_STATE="expected-state")
def test_microsoft_push_skips_unknown_subscription(_patch_sync_delay):
    resp = _post_json(Client(), f"{BASE}/microsoft", {
        "value": [{"subscriptionId": "no-such-sub", "clientState": "expected-state"}],
    })
    assert resp.status_code == 202
    assert _patch_sync_delay == []


@pytest.mark.django_db
def test_microsoft_push_empty_notifications_is_202(_patch_sync_delay):
    resp = _post_json(Client(), f"{BASE}/microsoft", {"value": []})
    assert resp.status_code == 202
    assert _patch_sync_delay == []


# ── /webhooks/mailcow ────────────────────────────────────────────────────


@pytest.mark.django_db
@override_settings(MICROSOFT_WEBHOOK_CLIENT_STATE="shared-secret")
def test_mailcow_push_401_when_secret_wrong(_patch_sync_delay):
    resp = _post_json(
        Client(), f"{BASE}/mailcow", {"address": "corp@example.com"},
        HTTP_X_MAILCOW_SECRET="nope",
    )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid secret"
    assert _patch_sync_delay == []


@pytest.mark.django_db
@override_settings(MICROSOFT_WEBHOOK_CLIENT_STATE="shared-secret")
def test_mailcow_push_204_and_enqueues_sync_when_account_known(_patch_sync_delay):
    mb = ProvisionedMailbox.objects.create(
        local_part="corp", domain="corp.example.com", address="corp-mb@corp.example.com",
    )
    acc = EmailAccount.objects.create(
        user_id=1, type=AccountType.CORPORATE, provider=AccountProvider.MAILCOW,
        address="corp@example.com", mailbox_id=mb.id,
    )
    resp = _post_json(
        Client(), f"{BASE}/mailcow", {"address": "corp@example.com"},
        HTTP_X_MAILCOW_SECRET="shared-secret",
    )
    assert resp.status_code == 204
    assert len(_patch_sync_delay) == 1
    assert _patch_sync_delay[0][0] == (acc.id,)


@pytest.mark.django_db
@override_settings(MICROSOFT_WEBHOOK_CLIENT_STATE="")
def test_mailcow_push_204_when_no_secret_configured_and_account_unknown(_patch_sync_delay):
    resp = _post_json(Client(), f"{BASE}/mailcow", {"address": "nobody@example.com"})
    assert resp.status_code == 204
    assert _patch_sync_delay == []


@pytest.mark.django_db
@override_settings(MICROSOFT_WEBHOOK_CLIENT_STATE="")
def test_mailcow_push_204_when_no_address_in_body(_patch_sync_delay):
    resp = _post_json(Client(), f"{BASE}/mailcow", {})
    assert resp.status_code == 204
    assert _patch_sync_delay == []
