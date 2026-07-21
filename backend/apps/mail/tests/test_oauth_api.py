"""Контракт /api/email/v1/oauth/* — паритет с
services/email/app/api/v1/oauth.py (5 эндпойнтов):

  GET    /oauth/status              — легаси-совместимость (последний токен)
  GET    /oauth/accounts            — сырой список OAuthToken (легаси picker)
  POST   /oauth/connect/{provider}  — старт PKCE-флоу (state -> cache)
  GET    /oauth/callback            — редирект провайдера, БЕЗ JWT
  DELETE /oauth/disconnect          — bulk-шим, дропает все personal-аккаунты

Авторизация (решение 3 брифа): все — auth="jwt", КРОМЕ callback — это
редирект ПРОВАЙДЕРА без Authorization-заголовка; идентичность приходит из
state-нонса (см. oauth_service.connect/callback) -> auth=None (буквальный
порт: роутер исходника тоже без get_current_user на этом пути).

State персистится в django.core.cache.cache (LocMemCache в тестах) вместо
прямого Redis-клиента исходника (решение конструктора oauth_service.py) —
поведение то же: одноразовый нонс с TTL, связывающий callback с исходным
user_id/provider/code_verifier.
"""
import datetime

import pytest
from django.core.cache import cache
from django.test import Client

from apps.mail.models import AccountType, EmailAccount, OAuthToken
from apps.mail.services import oauth_clients, oauth_service
from apps.mail.services.oauth_clients import TokenBundle
from apps.users.models import User, UserStatus
from htqweb.authn.jwt import issue_token_pair

BASE = "/api/email/v1/oauth"


@pytest.fixture
def user(db):
    u = User.objects.create(
        username="oauth-user", email="oauth@htq.test", password="x", status=UserStatus.ACTIVE,
    )
    u.set_password("S3cret!")
    u.save()
    return u


@pytest.fixture
def auth(user):
    return {"HTTP_AUTHORIZATION": f"Bearer {issue_token_pair(user)['access']}"}


def _token(user_id, **kw):
    defaults = dict(
        user_id=user_id, provider="google", provider_account_id="acct@example.com",
        encrypted_access_token="enc-access", expires_at=datetime.datetime.now(datetime.timezone.utc),
    )
    defaults.update(kw)
    return OAuthToken.objects.create(**defaults)


class FakeOAuthClient:
    """Стенд-ин для GoogleOAuthClient/MicrosoftOAuthClient — исходник бьёт в
    реальные https://accounts.google.com/..., что недопустимо в юнит-тестах
    (см. monkeypatch.setattr(oauth_service, "get_oauth_client", ...) ниже,
    тот же паттерн, что apps/hr/tests/test_department_files_api.py::
    fake_media_storage для get_storage)."""

    def __init__(self, provider="google", *, email="new@example.com", name="New User",
                 access_token="fresh-access", refresh_token="fresh-refresh", expires_in=3600):
        self.provider = provider
        self._email = email
        self._name = name
        self._access_token = access_token
        self._refresh_token = refresh_token
        self._expires_in = expires_in
        self.revoked = []

    def build_auth_url(self, state, code_challenge):
        return f"https://fake.example/auth?state={state}&challenge={code_challenge}"

    def exchange_code(self, code, code_verifier):
        return TokenBundle(
            access_token=self._access_token, refresh_token=self._refresh_token,
            expires_in=self._expires_in, scope="scope",
        )

    def userinfo(self, access_token):
        if self.provider == "google":
            return {"email": self._email, "name": self._name}
        return {"mail": self._email, "displayName": self._name}

    def revoke(self, token):
        self.revoked.append(token)


# ── GET /oauth/status ────────────────────────────────────────────────────

@pytest.mark.django_db
def test_status_requires_jwt():
    assert Client().get(f"{BASE}/status").status_code == 401


@pytest.mark.django_db
def test_status_not_connected_when_no_token(auth):
    resp = Client().get(f"{BASE}/status", **auth)
    assert resp.status_code == 200
    assert resp.json() == {
        "connected": False, "provider": None, "email": None,
        "primary_email": None, "connected_at": None, "token_expires_at": None,
    }


@pytest.mark.django_db
def test_status_reports_most_recent_token(user, auth):
    _token(user.id, provider_account_id="old@example.com")
    newest = _token(user.id, provider="microsoft", provider_account_id="new@example.com")

    resp = Client().get(f"{BASE}/status", **auth)
    assert resp.status_code == 200
    body = resp.json()
    assert body["connected"] is True
    assert body["provider"] == "microsoft"
    assert body["email"] == "new@example.com"
    assert body["primary_email"] == "new@example.com"
    assert body["token_expires_at"] is not None
    assert newest.id  # sanity


# ── GET /oauth/accounts ──────────────────────────────────────────────────

@pytest.mark.django_db
def test_oauth_accounts_requires_jwt():
    assert Client().get(f"{BASE}/accounts").status_code == 401


@pytest.mark.django_db
def test_oauth_accounts_scoped_to_user(user, auth):
    other = User.objects.create(username="x2", email="x2@htq.test", password="x", status=UserStatus.ACTIVE)
    mine = _token(user.id)
    _token(other.id)

    resp = Client().get(f"{BASE}/accounts", **auth)
    assert resp.status_code == 200
    body = resp.json()
    assert [t["id"] for t in body] == [mine.id]
    assert {"id", "provider", "provider_account_id", "expires_at", "is_active"} == set(body[0])


# ── POST /oauth/connect/{provider} ───────────────────────────────────────

@pytest.mark.django_db
def test_connect_requires_jwt():
    assert Client().post(f"{BASE}/connect/google").status_code == 401


@pytest.mark.django_db
def test_connect_rejects_unknown_provider(auth):
    resp = Client().post(f"{BASE}/connect/yahoo", **auth)
    assert resp.status_code == 422


@pytest.mark.django_db
def test_connect_503_when_not_configured(auth, settings):
    settings.GOOGLE_CLIENT_ID = ""
    settings.GOOGLE_CLIENT_SECRET = ""
    resp = Client().post(f"{BASE}/connect/google", **auth)
    assert resp.status_code == 503
    assert resp.json()["detail"] == "Google OAuth not configured"


@pytest.mark.django_db
def test_connect_returns_auth_url_and_persists_state(user, auth, settings):
    settings.GOOGLE_CLIENT_ID = "client-id"
    settings.GOOGLE_CLIENT_SECRET = "client-secret"

    resp = Client().post(f"{BASE}/connect/google", **auth)
    assert resp.status_code == 200
    body = resp.json()
    assert body["provider"] == "google"
    assert body["auth_url"].startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert "state" in body["auth_url"]

    state = body["state"]
    cached = cache.get(f"mail:oauth:state:{state}")
    assert cached["user_id"] == user.id
    assert cached["provider"] == "google"
    assert "code_verifier" in cached


# ── GET /oauth/callback ───────────────────────────────────────────────────

@pytest.mark.django_db
def test_callback_400_on_provider_error():
    resp = Client().get(f"{BASE}/callback", {"code": "x", "state": "y", "error": "access_denied"})
    assert resp.status_code == 400


@pytest.mark.django_db
def test_callback_400_on_invalid_or_missing_state():
    resp = Client().get(f"{BASE}/callback", {"code": "x", "state": "does-not-exist"})
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Invalid or expired state"


@pytest.mark.django_db
def test_callback_422_when_missing_query_params():
    assert Client().get(f"{BASE}/callback").status_code == 422


@pytest.mark.django_db
def test_callback_creates_token_and_account_no_jwt_required(monkeypatch, user):
    fake = FakeOAuthClient(provider="google", email="fresh@gmail.com", name="Fresh User")
    monkeypatch.setattr(oauth_service, "get_oauth_client", lambda provider: fake)

    cache.set("mail:oauth:state:nonce123", {
        "user_id": user.id, "provider": "google", "code_verifier": "verifier",
    }, timeout=600)

    resp = Client().get(f"{BASE}/callback", {"code": "auth-code", "state": "nonce123"})
    assert resp.status_code == 200
    body = resp.json()
    assert body == {
        "status": "ok", "provider": "google", "address": "fresh@gmail.com",
        "account_id": body["account_id"],
    }

    # State одноразовый — второй проход с тем же state падает.
    assert cache.get("mail:oauth:state:nonce123") is None

    token = OAuthToken.objects.get(user_id=user.id, provider="google")
    assert token.encrypted_access_token != "fresh-access"  # зашифрован
    from apps.mail.services.crypto import crypto_service
    assert crypto_service.decrypt(token.encrypted_access_token) == "fresh-access"
    assert crypto_service.decrypt(token.encrypted_refresh_token) == "fresh-refresh"

    account = EmailAccount.objects.get(user_id=user.id, address="fresh@gmail.com")
    assert account.type == AccountType.PERSONAL
    assert account.provider == "google"
    assert account.display_name == "Fresh User"
    assert account.is_default is True  # первый аккаунт пользователя -> дефолт
    assert account.oauth_token_id == token.id


@pytest.mark.django_db
def test_callback_upserts_existing_account_and_token(monkeypatch, user):
    existing_token = _token(user.id, provider="google", provider_account_id="repeat@gmail.com")
    existing_account = EmailAccount.objects.create(
        user_id=user.id, type=AccountType.PERSONAL, provider="google",
        address="repeat@gmail.com", oauth_token=existing_token, is_default=True,
    )

    fake = FakeOAuthClient(provider="google", email="repeat@gmail.com", name="Repeat User")
    monkeypatch.setattr(oauth_service, "get_oauth_client", lambda provider: fake)
    cache.set("mail:oauth:state:nonce456", {
        "user_id": user.id, "provider": "google", "code_verifier": "verifier",
    }, timeout=600)

    resp = Client().get(f"{BASE}/callback", {"code": "auth-code", "state": "nonce456"})
    assert resp.status_code == 200
    assert resp.json()["account_id"] == existing_account.id
    assert OAuthToken.objects.filter(user_id=user.id, provider="google").count() == 1

    existing_account.refresh_from_db()
    assert existing_account.is_default is True  # уже был дефолтом — не трогаем


@pytest.mark.django_db
def test_callback_502_when_provider_email_missing(monkeypatch, user):
    fake = FakeOAuthClient(provider="google", email=None)
    monkeypatch.setattr(oauth_service, "get_oauth_client", lambda provider: fake)
    cache.set("mail:oauth:state:nonce789", {
        "user_id": user.id, "provider": "google", "code_verifier": "verifier",
    }, timeout=600)

    resp = Client().get(f"{BASE}/callback", {"code": "auth-code", "state": "nonce789"})
    assert resp.status_code == 502


# ── DELETE /oauth/disconnect ──────────────────────────────────────────────

@pytest.mark.django_db
def test_disconnect_requires_jwt():
    assert Client().delete(f"{BASE}/disconnect").status_code == 401


@pytest.mark.django_db
def test_disconnect_drops_only_personal_accounts(user, auth, monkeypatch):
    fake = FakeOAuthClient()
    monkeypatch.setattr(oauth_service, "get_oauth_client", lambda provider: fake)
    monkeypatch.setattr(
        oauth_service.crypto_service, "decrypt", lambda enc: "plain-token",
    )

    tok = _token(user.id)
    personal = EmailAccount.objects.create(
        user_id=user.id, type=AccountType.PERSONAL, provider="google",
        address="personal@example.com", oauth_token=tok,
    )
    corporate = EmailAccount.objects.create(
        user_id=user.id, type=AccountType.CORPORATE, provider="mailcow",
        address="corp@example.com", mailbox_id=55,
    )

    resp = Client().delete(f"{BASE}/disconnect", **auth)
    assert resp.status_code == 200
    assert resp.json() == {"status": "disconnected", "count": 1}

    assert not EmailAccount.objects.filter(id=personal.id).exists()
    assert EmailAccount.objects.filter(id=corporate.id).exists()
    assert not OAuthToken.objects.filter(id=tok.id).exists()
    assert fake.revoked == ["plain-token"]
