"""HTTP-клиенты Google/Microsoft OAuth 2.0 c PKCE — порт
``services/email/app/services/oauth_clients.py``.

СИНХРОННЫЙ (``httpx.Client``, а не ``AsyncClient``): Django-вьюхи этого
домена синхронные (``htqweb.http.api_view``), в отличие от asyncio
FastAPI-исходника — сама HTTP-механика (PKCE, token exchange, userinfo,
revoke) переносится один в один, меняется только клиент httpx.

Push-подписки (Gmail watch / Graph subscriptions, "Phase 5" исходника) НЕ
портируются здесь — ``accounts.py``/``oauth.py`` (единственные роутеры этой
под-задачи) их не вызывают вовсе; появятся вместе с под-задачей workers.

Настройки — то же решение 2 брифа, что и ``apps/mail/services/crypto.py``:
``htqweb/settings`` трогать нельзя (вне зоны ``backend/apps/mail/**``),
поэтому client_id/secret/redirect_uri читаются через
``getattr(django.conf.settings, NAME, <дефолт>)`` прямо здесь. Пустая строка
по умолчанию для client_id/secret — НЕ баг, а буквальный перенос поведения
исходника: ``oauth_service.connect()`` проверяет ``client_id and
client_secret`` и отдаёт 503 "OAuth not configured", если оператор не задал
реальные ``GOOGLE_CLIENT_ID``/``GOOGLE_CLIENT_SECRET``/... (любым способом —
env, ``override_settings`` в тестах, или будущей правкой settings, которая
уже вне зоны этой под-задачи).
"""
from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlencode

import httpx
from django.conf import settings

_DEFAULT_REDIRECT_URI = "http://localhost:3000/email/oauth/callback/"


def _setting(name: str, default):
    return getattr(settings, name, default)


@dataclass(frozen=True)
class TokenBundle:
    """Provider-agnostic token exchange result."""

    access_token: str
    refresh_token: str | None
    expires_in: int  # seconds until access_token expires
    scope: str | None = None


def gen_pkce_pair() -> tuple[str, str]:
    """Return ``(code_verifier, code_challenge)`` per RFC 7636."""
    verifier = (
        base64.urlsafe_b64encode(secrets.token_bytes(64)).rstrip(b"=").decode("ascii")
    )
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
        .rstrip(b"=")
        .decode("ascii")
    )
    return verifier, challenge


def gen_state_nonce() -> str:
    """Random opaque ID used as the OAuth ``state`` parameter."""
    return secrets.token_urlsafe(24)


class OAuthClient(Protocol):
    """Common surface for both providers."""

    provider: str

    def build_auth_url(self, state: str, code_challenge: str) -> str: ...
    def exchange_code(self, code: str, code_verifier: str) -> TokenBundle: ...
    def refresh(self, refresh_token: str) -> TokenBundle: ...
    def userinfo(self, access_token: str) -> dict: ...
    def revoke(self, token: str) -> None: ...


# ────────────────────────────────────────────────────────────────────────
# Google
# ────────────────────────────────────────────────────────────────────────


class GoogleOAuthClient:
    provider = "google"

    AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
    TOKEN_URL = "https://oauth2.googleapis.com/token"
    USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"
    REVOKE_URL = "https://oauth2.googleapis.com/revoke"

    SCOPES = (
        "https://www.googleapis.com/auth/gmail.modify",
        "https://www.googleapis.com/auth/userinfo.email",
        "https://www.googleapis.com/auth/userinfo.profile",
    )

    def build_auth_url(self, state: str, code_challenge: str) -> str:
        params = {
            "client_id": _setting("GOOGLE_CLIENT_ID", ""),
            "redirect_uri": _setting("GOOGLE_OAUTH_REDIRECT_URI", _DEFAULT_REDIRECT_URI),
            "response_type": "code",
            "scope": " ".join(self.SCOPES),
            "state": state,
            "access_type": "offline",
            "prompt": "consent",
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        return f"{self.AUTH_URL}?{urlencode(params)}"

    def exchange_code(self, code: str, code_verifier: str) -> TokenBundle:
        with httpx.Client(timeout=10.0) as c:
            r = c.post(
                self.TOKEN_URL,
                data={
                    "code": code,
                    "client_id": _setting("GOOGLE_CLIENT_ID", ""),
                    "client_secret": _setting("GOOGLE_CLIENT_SECRET", ""),
                    "redirect_uri": _setting("GOOGLE_OAUTH_REDIRECT_URI", _DEFAULT_REDIRECT_URI),
                    "grant_type": "authorization_code",
                    "code_verifier": code_verifier,
                },
            )
            r.raise_for_status()
            data = r.json()
        return TokenBundle(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token"),
            expires_in=int(data.get("expires_in", 3600)),
            scope=data.get("scope"),
        )

    def refresh(self, refresh_token: str) -> TokenBundle:
        with httpx.Client(timeout=10.0) as c:
            r = c.post(
                self.TOKEN_URL,
                data={
                    "refresh_token": refresh_token,
                    "client_id": _setting("GOOGLE_CLIENT_ID", ""),
                    "client_secret": _setting("GOOGLE_CLIENT_SECRET", ""),
                    "grant_type": "refresh_token",
                },
            )
            r.raise_for_status()
            data = r.json()
        return TokenBundle(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token"),
            expires_in=int(data.get("expires_in", 3600)),
            scope=data.get("scope"),
        )

    def userinfo(self, access_token: str) -> dict:
        with httpx.Client(timeout=10.0) as c:
            r = c.get(
                self.USERINFO_URL,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            r.raise_for_status()
            return r.json()

    def revoke(self, token: str) -> None:
        # Best-effort — Google returns 200 on success, 400 if already revoked.
        with httpx.Client(timeout=10.0) as c:
            try:
                c.post(
                    self.REVOKE_URL,
                    data={"token": token},
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
            except httpx.HTTPError:
                pass


# ────────────────────────────────────────────────────────────────────────
# Microsoft (Azure AD / Microsoft Graph)
# ────────────────────────────────────────────────────────────────────────


class MicrosoftOAuthClient:
    provider = "microsoft"

    USERINFO_URL = "https://graph.microsoft.com/v1.0/me"
    SCOPES = (
        "Mail.ReadWrite",
        "Mail.Send",
        "offline_access",
        "User.Read",
    )

    @property
    def AUTH_URL(self) -> str:
        tenant = _setting("MICROSOFT_OAUTH_TENANT_ID", "common")
        return f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize"

    @property
    def TOKEN_URL(self) -> str:
        tenant = _setting("MICROSOFT_OAUTH_TENANT_ID", "common")
        return f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"

    def build_auth_url(self, state: str, code_challenge: str) -> str:
        params = {
            "client_id": _setting("MICROSOFT_CLIENT_ID", ""),
            "redirect_uri": _setting("MICROSOFT_OAUTH_REDIRECT_URI", _DEFAULT_REDIRECT_URI),
            "response_type": "code",
            "scope": " ".join(self.SCOPES),
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "prompt": "select_account",
        }
        return f"{self.AUTH_URL}?{urlencode(params)}"

    def exchange_code(self, code: str, code_verifier: str) -> TokenBundle:
        with httpx.Client(timeout=10.0) as c:
            r = c.post(
                self.TOKEN_URL,
                data={
                    "code": code,
                    "client_id": _setting("MICROSOFT_CLIENT_ID", ""),
                    "client_secret": _setting("MICROSOFT_CLIENT_SECRET", ""),
                    "redirect_uri": _setting("MICROSOFT_OAUTH_REDIRECT_URI", _DEFAULT_REDIRECT_URI),
                    "grant_type": "authorization_code",
                    "code_verifier": code_verifier,
                    "scope": " ".join(self.SCOPES),
                },
            )
            r.raise_for_status()
            data = r.json()
        return TokenBundle(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token"),
            expires_in=int(data.get("expires_in", 3600)),
            scope=data.get("scope"),
        )

    def refresh(self, refresh_token: str) -> TokenBundle:
        with httpx.Client(timeout=10.0) as c:
            r = c.post(
                self.TOKEN_URL,
                data={
                    "refresh_token": refresh_token,
                    "client_id": _setting("MICROSOFT_CLIENT_ID", ""),
                    "client_secret": _setting("MICROSOFT_CLIENT_SECRET", ""),
                    "grant_type": "refresh_token",
                    "scope": " ".join(self.SCOPES),
                },
            )
            r.raise_for_status()
            data = r.json()
        return TokenBundle(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token"),
            expires_in=int(data.get("expires_in", 3600)),
            scope=data.get("scope"),
        )

    def userinfo(self, access_token: str) -> dict:
        with httpx.Client(timeout=10.0) as c:
            r = c.get(
                self.USERINFO_URL,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            r.raise_for_status()
            return r.json()

    def revoke(self, token: str) -> None:
        # Microsoft has no per-token revocation endpoint for personal
        # accounts — local cleanup (delete the token row) is enough.
        return None


def get_oauth_client(provider: str) -> OAuthClient:
    """Factory used by apps/mail/services/{account,oauth}_service.py."""
    if provider == "google":
        return GoogleOAuthClient()
    if provider == "microsoft":
        return MicrosoftOAuthClient()
    raise ValueError(f"Unsupported OAuth provider: {provider!r}")
