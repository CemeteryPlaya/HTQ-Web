"""Контракт ensure_fresh_token (sync/gmail.py, sync/microsoft.py) — порт
``_ensure_fresh_token`` исходника. БЕЗ живой сети — провайдерский
``.refresh()`` монkeypatch'ится (тот же seam, что и в
apps/mail/tests/test_oauth_api.py для connect/callback)."""
import datetime

import pytest

from apps.mail.models import AccountProvider, AccountType, EmailAccount, OAuthToken, ProvisionedMailbox
from apps.mail.services.crypto import crypto_service
from apps.mail.services.oauth_clients import TokenBundle
from apps.mail.services.sync import gmail as sync_gmail
from apps.mail.services.sync import microsoft as sync_microsoft


def _account(provider, expires_delta, *, with_refresh=True):
    expires_at = datetime.datetime.now(datetime.timezone.utc) + expires_delta
    tok = OAuthToken.objects.create(
        user_id=1, provider=provider, provider_account_id="acct@example.com",
        encrypted_access_token=crypto_service.encrypt("old-access"),
        encrypted_refresh_token=crypto_service.encrypt("old-refresh") if with_refresh else None,
        expires_at=expires_at,
    )
    return EmailAccount.objects.create(
        user_id=1, type=AccountType.PERSONAL,
        provider=AccountProvider.GOOGLE if provider == "google" else AccountProvider.MICROSOFT,
        address="acct@example.com", oauth_token=tok,
    )


@pytest.mark.django_db
def test_gmail_ensure_fresh_token_returns_decrypted_without_refresh_when_valid():
    account = _account("google", datetime.timedelta(hours=1))
    access = sync_gmail.ensure_fresh_token(account)
    assert access == "old-access"


@pytest.mark.django_db
def test_gmail_ensure_fresh_token_refreshes_when_expired(monkeypatch):
    account = _account("google", -datetime.timedelta(minutes=5))

    called = {}

    def _fake_refresh(self, refresh_token):
        called["refresh_token"] = refresh_token
        return TokenBundle(access_token="new-access", refresh_token="new-refresh", expires_in=3600)

    from apps.mail.services.oauth_clients import GoogleOAuthClient
    monkeypatch.setattr(GoogleOAuthClient, "refresh", _fake_refresh)

    access = sync_gmail.ensure_fresh_token(account)
    assert access == "new-access"
    assert called["refresh_token"] == "old-refresh"

    account.oauth_token.refresh_from_db()
    assert crypto_service.decrypt(account.oauth_token.encrypted_access_token) == "new-access"
    assert crypto_service.decrypt(account.oauth_token.encrypted_refresh_token) == "new-refresh"
    assert account.oauth_token.expires_at > datetime.datetime.now(datetime.timezone.utc)


@pytest.mark.django_db
def test_gmail_ensure_fresh_token_raises_without_refresh_token():
    account = _account("google", -datetime.timedelta(minutes=5), with_refresh=False)
    with pytest.raises(RuntimeError, match="no refresh_token"):
        sync_gmail.ensure_fresh_token(account)


@pytest.mark.django_db
def test_gmail_ensure_fresh_token_raises_when_oauth_token_missing():
    mb = ProvisionedMailbox.objects.create(
        local_part="corp", domain="corp.example.com", address="corp-mb@corp.example.com",
    )
    account = EmailAccount.objects.create(
        user_id=1, type=AccountType.CORPORATE, provider=AccountProvider.MAILCOW,
        address="corp@example.com", mailbox_id=mb.id,
    )
    with pytest.raises(RuntimeError, match="OAuthToken missing"):
        sync_gmail.ensure_fresh_token(account)


@pytest.mark.django_db
def test_microsoft_ensure_fresh_token_refreshes_when_expired(monkeypatch):
    account = _account("microsoft", -datetime.timedelta(minutes=5))

    def _fake_refresh(self, refresh_token):
        return TokenBundle(access_token="ms-new-access", refresh_token=None, expires_in=1800)

    from apps.mail.services.oauth_clients import MicrosoftOAuthClient
    monkeypatch.setattr(MicrosoftOAuthClient, "refresh", _fake_refresh)

    access = sync_microsoft.ensure_fresh_token(account)
    assert access == "ms-new-access"
    account.oauth_token.refresh_from_db()
    # Microsoft may omit refresh_token in the bundle — old one is kept.
    assert crypto_service.decrypt(account.oauth_token.encrypted_refresh_token) == "old-refresh"
