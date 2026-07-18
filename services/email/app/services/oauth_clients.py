"""HTTP clients for Google and Microsoft OAuth 2.0 (with PKCE).

Both providers expose the same shape via :class:`OAuthClient` so the
``oauth.py`` router can switch on provider name and stay flat. Each call
is a single ``httpx`` request with a 10s timeout — provider rate-limits
and per-call retries are the caller's responsibility.

Phase 3 covers the basics: PKCE state, token exchange, refresh, user
info, revoke. Push-subscription helpers (Gmail watch, Graph
subscriptions) land in Phase 5 alongside the webhook receivers.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlencode

import httpx

from app.core.settings import settings


@dataclass(frozen=True)
class TokenBundle:
    """Provider-agnostic token exchange result."""

    access_token: str
    refresh_token: str | None
    expires_in: int  # seconds until access_token expires
    scope: str | None = None


def gen_pkce_pair() -> tuple[str, str]:
    """Return ``(code_verifier, code_challenge)`` per RFC 7636.

    Verifier is 64 random bytes → urlsafe base64 (no padding) → 86 chars,
    well within the 43–128 range. Challenge is the S256 of the verifier.
    """
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
    async def exchange_code(self, code: str, code_verifier: str) -> TokenBundle: ...
    async def refresh(self, refresh_token: str) -> TokenBundle: ...
    async def userinfo(self, access_token: str) -> dict: ...
    async def revoke(self, token: str) -> None: ...


# ────────────────────────────────────────────────────────────────────────
# Google
# ────────────────────────────────────────────────────────────────────────


class GoogleOAuthClient:
    provider = "google"

    AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
    TOKEN_URL = "https://oauth2.googleapis.com/token"
    USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"
    REVOKE_URL = "https://oauth2.googleapis.com/revoke"

    # gmail.modify covers read + send + label changes (no access to settings).
    SCOPES = (
        "https://www.googleapis.com/auth/gmail.modify",
        "https://www.googleapis.com/auth/userinfo.email",
        "https://www.googleapis.com/auth/userinfo.profile",
    )

    def build_auth_url(self, state: str, code_challenge: str) -> str:
        params = {
            "client_id": settings.google_client_id,
            "redirect_uri": settings.google_oauth_redirect_uri,
            "response_type": "code",
            "scope": " ".join(self.SCOPES),
            "state": state,
            # offline + consent are required to receive a refresh_token
            # on every authorisation (Google only sends it once otherwise).
            "access_type": "offline",
            "prompt": "consent",
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        return f"{self.AUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str, code_verifier: str) -> TokenBundle:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.post(
                self.TOKEN_URL,
                data={
                    "code": code,
                    "client_id": settings.google_client_id,
                    "client_secret": settings.google_client_secret,
                    "redirect_uri": settings.google_oauth_redirect_uri,
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

    async def refresh(self, refresh_token: str) -> TokenBundle:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.post(
                self.TOKEN_URL,
                data={
                    "refresh_token": refresh_token,
                    "client_id": settings.google_client_id,
                    "client_secret": settings.google_client_secret,
                    "grant_type": "refresh_token",
                },
            )
            r.raise_for_status()
            data = r.json()
        return TokenBundle(
            access_token=data["access_token"],
            # Google may rotate refresh tokens — keep the old one if absent.
            refresh_token=data.get("refresh_token"),
            expires_in=int(data.get("expires_in", 3600)),
            scope=data.get("scope"),
        )

    async def userinfo(self, access_token: str) -> dict:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.get(
                self.USERINFO_URL,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            r.raise_for_status()
            return r.json()  # {"email", "verified_email", "name", "picture", ...}

    async def revoke(self, token: str) -> None:
        # Best-effort — Google returns 200 on success, 400 if already revoked.
        async with httpx.AsyncClient(timeout=10.0) as c:
            try:
                await c.post(
                    self.REVOKE_URL,
                    data={"token": token},
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
            except httpx.HTTPError:
                pass

    # ── Push (Phase 5) ──────────────────────────────────────────────────
    WATCH_URL = "https://gmail.googleapis.com/gmail/v1/users/me/watch"
    STOP_URL = "https://gmail.googleapis.com/gmail/v1/users/me/stop"

    async def start_watch(
        self, access_token: str, *, topic: str, label_ids: list[str] | None = None
    ) -> dict:
        """Register a Gmail watch on Pub/Sub. Returns ``{historyId, expiration}``."""
        body: dict = {"topicName": topic}
        if label_ids:
            body["labelIds"] = label_ids
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.post(
                self.WATCH_URL,
                headers={"Authorization": f"Bearer {access_token}"},
                json=body,
            )
            r.raise_for_status()
            return r.json()

    async def stop_watch(self, access_token: str) -> None:
        async with httpx.AsyncClient(timeout=10.0) as c:
            try:
                await c.post(
                    self.STOP_URL,
                    headers={"Authorization": f"Bearer {access_token}"},
                )
            except httpx.HTTPError:
                pass


# ────────────────────────────────────────────────────────────────────────
# Microsoft (Azure AD / Microsoft Graph)
# ────────────────────────────────────────────────────────────────────────


class MicrosoftOAuthClient:
    provider = "microsoft"

    USERINFO_URL = "https://graph.microsoft.com/v1.0/me"
    # Mail.ReadWrite + Mail.Send for inbox sync + outbox; offline_access
    # for refresh tokens; User.Read for /me identity probe.
    SCOPES = (
        "Mail.ReadWrite",
        "Mail.Send",
        "offline_access",
        "User.Read",
    )

    @property
    def AUTH_URL(self) -> str:
        return (
            f"https://login.microsoftonline.com/"
            f"{settings.microsoft_oauth_tenant_id}/oauth2/v2.0/authorize"
        )

    @property
    def TOKEN_URL(self) -> str:
        return (
            f"https://login.microsoftonline.com/"
            f"{settings.microsoft_oauth_tenant_id}/oauth2/v2.0/token"
        )

    def build_auth_url(self, state: str, code_challenge: str) -> str:
        params = {
            "client_id": settings.microsoft_client_id,
            "redirect_uri": settings.microsoft_oauth_redirect_uri,
            "response_type": "code",
            "scope": " ".join(self.SCOPES),
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            # Force account picker so users on multi-account devices land
            # on the right inbox.
            "prompt": "select_account",
        }
        return f"{self.AUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str, code_verifier: str) -> TokenBundle:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.post(
                self.TOKEN_URL,
                data={
                    "code": code,
                    "client_id": settings.microsoft_client_id,
                    "client_secret": settings.microsoft_client_secret,
                    "redirect_uri": settings.microsoft_oauth_redirect_uri,
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

    async def refresh(self, refresh_token: str) -> TokenBundle:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.post(
                self.TOKEN_URL,
                data={
                    "refresh_token": refresh_token,
                    "client_id": settings.microsoft_client_id,
                    "client_secret": settings.microsoft_client_secret,
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

    async def userinfo(self, access_token: str) -> dict:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.get(
                self.USERINFO_URL,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            r.raise_for_status()
            return r.json()  # {"mail", "userPrincipalName", "displayName", ...}

    async def revoke(self, token: str) -> None:
        # Microsoft has no per-token revocation endpoint for personal
        # accounts. Real revocation happens client-side at sign-out
        # (https://login.microsoftonline.com/.../oauth2/v2.0/logout).
        # Local cleanup (delete the token row) is enough for our needs.
        return None

    # ── Push (Phase 5) ──────────────────────────────────────────────────
    SUBSCRIPTIONS_URL = "https://graph.microsoft.com/v1.0/subscriptions"

    async def create_subscription(
        self,
        access_token: str,
        *,
        resource: str,
        notification_url: str,
        client_state: str,
        expiration_iso: str,
    ) -> dict:
        body = {
            "changeType": "created,updated,deleted",
            "notificationUrl": notification_url,
            "resource": resource,
            "expirationDateTime": expiration_iso,
            "clientState": client_state,
        }
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.post(
                self.SUBSCRIPTIONS_URL,
                headers={"Authorization": f"Bearer {access_token}"},
                json=body,
            )
            r.raise_for_status()
            return r.json()

    async def renew_subscription(
        self, access_token: str, *, subscription_id: str, expiration_iso: str
    ) -> dict:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.patch(
                f"{self.SUBSCRIPTIONS_URL}/{subscription_id}",
                headers={"Authorization": f"Bearer {access_token}"},
                json={"expirationDateTime": expiration_iso},
            )
            r.raise_for_status()
            return r.json()

    async def delete_subscription(self, access_token: str, subscription_id: str) -> None:
        async with httpx.AsyncClient(timeout=10.0) as c:
            try:
                await c.delete(
                    f"{self.SUBSCRIPTIONS_URL}/{subscription_id}",
                    headers={"Authorization": f"Bearer {access_token}"},
                )
            except httpx.HTTPError:
                pass


def get_oauth_client(provider: str) -> OAuthClient:
    """Factory used by the OAuth router."""
    if provider == "google":
        return GoogleOAuthClient()
    if provider == "microsoft":
        return MicrosoftOAuthClient()
    raise ValueError(f"Unsupported OAuth provider: {provider!r}")
