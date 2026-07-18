"""OAuth API — real PKCE flow for Google and Microsoft.

Flow:
  1. Frontend ``POST /oauth/connect/{provider}`` with auth header.
     → backend mints a PKCE pair + state nonce, stashes
       ``{user_id, provider, code_verifier}`` in Redis with a 10-min
       TTL, returns ``{auth_url, state}``.
  2. Frontend redirects the browser to ``auth_url``.
  3. Provider sends the user back to ``GOOGLE_OAUTH_REDIRECT_URI``
     (a frontend page) with ``?code=&state=``.
  4. The frontend page calls ``GET /oauth/callback?code=&state=``
     (no auth header needed — state binds the request to the user).
  5. Backend looks up state in Redis, exchanges the code for tokens,
     pulls the provider's email via ``userinfo``, encrypts the tokens,
     upserts ``oauth_tokens`` + ``email_accounts`` (type=personal) and
     returns ``{status, account_id, address, provider}``.

Status / disconnect endpoints stay around as compatibility shims so the
existing ``frontend/src/services/emailService.ts`` page renders until
phase 9 replaces it.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import TokenPayload, get_current_user
from app.core.redis import get_redis
from app.core.settings import settings
from app.db import get_db_session
from app.models.account import EmailAccount
from app.models.email import OAuthToken
from app.schemas.email import OAuthTokenRead
from app.services.crypto import crypto_service
from app.services.oauth_clients import (
    OAuthClient,
    gen_pkce_pair,
    gen_state_nonce,
    get_oauth_client,
)


log = logging.getLogger(__name__)
router = APIRouter(tags=["oauth"])


# ────────────────────────────────────────────────────────────────────────
# Schemas
# ────────────────────────────────────────────────────────────────────────


class OAuthStatus(BaseModel):
    connected: bool
    provider: Literal["google", "microsoft"] | None = None
    email: str | None = None
    primary_email: str | None = None
    connected_at: str | None = None
    token_expires_at: str | None = None


class OAuthInitResponse(BaseModel):
    auth_url: str
    provider: str
    state: str


class OAuthCallbackResponse(BaseModel):
    status: Literal["ok"] = "ok"
    provider: str
    address: str
    account_id: int


# ────────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────────


def _state_key(nonce: str) -> str:
    return f"oauth:state:{nonce}"


def _extract_email(provider: str, info: dict) -> str:
    """Pull the canonical address out of a provider userinfo response."""
    if provider == "google":
        email = info.get("email")
    else:  # microsoft
        # `mail` may be null on personal Microsoft accounts; fall back to UPN.
        email = info.get("mail") or info.get("userPrincipalName")
    if not email:
        raise HTTPException(
            status_code=502,
            detail="Provider did not return an email address",
        )
    return email.lower()


def _display_name(provider: str, info: dict) -> str | None:
    if provider == "google":
        return info.get("name")
    return info.get("displayName")


# ────────────────────────────────────────────────────────────────────────
# Compatibility status / list (kept for the legacy SPA)
# ────────────────────────────────────────────────────────────────────────


@router.get("/status", response_model=OAuthStatus)
async def oauth_status(
    session: AsyncSession = Depends(get_db_session),
    user: TokenPayload = Depends(get_current_user),
):
    """Most-recent personal OAuth account for the user, if any."""
    stmt = (
        select(OAuthToken)
        .where(OAuthToken.user_id == user.user_id)
        .order_by(OAuthToken.created_at.desc())
        .limit(1)
    )
    token = (await session.execute(stmt)).scalar_one_or_none()
    if token is None:
        return OAuthStatus(connected=False)
    return OAuthStatus(
        connected=True,
        provider=getattr(token, "provider", None),
        email=getattr(token, "provider_account_id", None),
        primary_email=getattr(token, "provider_account_id", None),
        connected_at=token.created_at.isoformat() if token.created_at else None,
        token_expires_at=token.expires_at.isoformat() if token.expires_at else None,
    )


@router.get("/accounts", response_model=list[OAuthTokenRead])
async def list_oauth_tokens(
    session: AsyncSession = Depends(get_db_session),
    user: TokenPayload = Depends(get_current_user),
):
    """Raw OAuthToken listing — kept for the legacy account-picker UI."""
    stmt = select(OAuthToken).where(OAuthToken.user_id == user.user_id)
    return list((await session.execute(stmt)).scalars().all())


# ────────────────────────────────────────────────────────────────────────
# Connect — start the PKCE dance
# ────────────────────────────────────────────────────────────────────────


@router.post("/connect/{provider}", response_model=OAuthInitResponse)
async def connect_account(
    provider: Literal["google", "microsoft"],
    user: TokenPayload = Depends(get_current_user),
):
    """Mint a state + PKCE pair, persist in Redis, return ``auth_url``."""
    client: OAuthClient = get_oauth_client(provider)

    # Guardrail — if env wasn't filled in yet, fail loudly instead of
    # redirecting users to a broken auth screen.
    if provider == "google" and not (
        settings.google_client_id and settings.google_client_secret
    ):
        raise HTTPException(status_code=503, detail="Google OAuth not configured")
    if provider == "microsoft" and not (
        settings.microsoft_client_id and settings.microsoft_client_secret
    ):
        raise HTTPException(status_code=503, detail="Microsoft OAuth not configured")

    code_verifier, code_challenge = gen_pkce_pair()
    nonce = gen_state_nonce()

    payload = json.dumps(
        {
            "user_id": user.user_id,
            "provider": provider,
            "code_verifier": code_verifier,
        }
    )
    redis = get_redis()
    await redis.set(_state_key(nonce), payload, ex=settings.oauth_state_ttl_sec)

    return OAuthInitResponse(
        auth_url=client.build_auth_url(state=nonce, code_challenge=code_challenge),
        provider=provider,
        state=nonce,
    )


# ────────────────────────────────────────────────────────────────────────
# Callback — exchange + persist
# ────────────────────────────────────────────────────────────────────────


@router.get("/callback", response_model=OAuthCallbackResponse)
async def oauth_callback(
    code: str = Query(..., min_length=1),
    state: str = Query(..., min_length=1),
    error: str | None = Query(None),
    session: AsyncSession = Depends(get_db_session),
):
    """Provider redirect target. Exchanges the code, persists, returns ack.

    No JWT — the ``state`` nonce in Redis binds the request to the
    originating user_id. State is single-use (deleted on lookup).
    """
    if error:
        raise HTTPException(status_code=400, detail=f"Provider error: {error}")

    redis = get_redis()
    raw = await redis.get(_state_key(state))
    if raw is None:
        raise HTTPException(status_code=400, detail="Invalid or expired state")
    # Single-use — drop before any provider call so a replay can't
    # double-mint accounts.
    await redis.delete(_state_key(state))

    payload = json.loads(raw)
    user_id: int = payload["user_id"]
    provider: str = payload["provider"]
    code_verifier: str = payload["code_verifier"]

    client: OAuthClient = get_oauth_client(provider)
    bundle = await client.exchange_code(code=code, code_verifier=code_verifier)
    info = await client.userinfo(bundle.access_token)
    address = _extract_email(provider, info)

    # Encrypt tokens at rest.
    enc_access = crypto_service.encrypt(bundle.access_token)
    enc_refresh = (
        crypto_service.encrypt(bundle.refresh_token) if bundle.refresh_token else None
    )
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=bundle.expires_in)

    # Upsert OAuthToken — keyed on (user_id, provider, provider_account_id).
    existing_token = (
        await session.execute(
            select(OAuthToken).where(
                OAuthToken.user_id == user_id,
                OAuthToken.provider == provider,
                OAuthToken.provider_account_id == address,
            )
        )
    ).scalar_one_or_none()

    if existing_token is None:
        token = OAuthToken(
            user_id=user_id,
            provider=provider,
            provider_account_id=address,
            encrypted_access_token=enc_access,
            encrypted_refresh_token=enc_refresh,
            expires_at=expires_at,
            is_active=True,
        )
        session.add(token)
        await session.flush()
    else:
        existing_token.encrypted_access_token = enc_access
        if enc_refresh:
            existing_token.encrypted_refresh_token = enc_refresh
        existing_token.expires_at = expires_at
        existing_token.is_active = True
        token = existing_token

    # Upsert EmailAccount.
    existing_account = (
        await session.execute(
            select(EmailAccount).where(
                EmailAccount.user_id == user_id,
                EmailAccount.address == address,
            )
        )
    ).scalar_one_or_none()

    # If the user has no default yet, this fresh account becomes default.
    has_default = (
        await session.execute(
            select(EmailAccount.id)
            .where(
                EmailAccount.user_id == user_id,
                EmailAccount.is_default.is_(True),
            )
            .limit(1)
        )
    ).scalar_one_or_none() is not None

    if existing_account is None:
        account = EmailAccount(
            user_id=user_id,
            type="personal",
            provider=provider,
            address=address,
            display_name=_display_name(provider, info),
            is_default=not has_default,
            is_active=True,
            oauth_token_id=token.id,
            sync_state={},
        )
        session.add(account)
    else:
        existing_account.is_active = True
        existing_account.oauth_token_id = token.id
        existing_account.display_name = (
            _display_name(provider, info) or existing_account.display_name
        )
        existing_account.last_sync_error = None
        account = existing_account

    await session.commit()
    await session.refresh(account)

    log.info(
        "oauth_connect_ok",
        extra={"user_id": user_id, "provider": provider, "account_id": account.id},
    )

    # Kick off initial backfill of the freshly-connected mailbox + push
    # registration (Pub/Sub watch for Gmail, Graph subscription for MS).
    try:
        from app.workers.sync_actors import register_account_push, start_account_sync
        start_account_sync.send(account.id)
        register_account_push.send(account.id)
    except Exception as exc:  # never fail the callback because of broker hiccups
        log.warning("post_oauth_enqueue_failed: %s", exc)

    return OAuthCallbackResponse(
        status="ok",
        provider=provider,
        address=address,
        account_id=account.id,
    )


# ────────────────────────────────────────────────────────────────────────
# Disconnect — bulk shim (kept for legacy frontend)
# ────────────────────────────────────────────────────────────────────────


@router.delete("/disconnect", status_code=status.HTTP_200_OK)
async def disconnect_all_personal(
    session: AsyncSession = Depends(get_db_session),
    user: TokenPayload = Depends(get_current_user),
):
    """Drop every personal account for the user.

    Best-effort revoke at provider, then delete tokens + email_accounts
    rows. Corporate (Mailcow) accounts stay untouched — they go through
    ``/mailboxes/{id}/archive/``.
    """
    accounts = (
        await session.execute(
            select(EmailAccount).where(
                EmailAccount.user_id == user.user_id,
                EmailAccount.type == "personal",
            )
        )
    ).scalars().all()

    for acc in accounts:
        if acc.oauth_token_id is None:
            continue
        token_row = await session.get(OAuthToken, acc.oauth_token_id)
        if token_row is not None:
            try:
                client = get_oauth_client(acc.provider)
                access = crypto_service.decrypt(token_row.encrypted_access_token)
                await client.revoke(access)
            except Exception as exc:  # best-effort
                log.warning("oauth_revoke_failed: %s", exc)

    # Delete email_accounts first (FK ondelete=SET NULL keeps oauth_tokens
    # but we drop those next anyway).
    await session.execute(
        delete(EmailAccount).where(
            EmailAccount.user_id == user.user_id,
            EmailAccount.type == "personal",
        )
    )
    await session.execute(
        delete(OAuthToken).where(OAuthToken.user_id == user.user_id)
    )
    await session.commit()
    return {"status": "disconnected", "count": len(accounts)}
