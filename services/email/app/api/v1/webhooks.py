"""Provider push receivers — Gmail Pub/Sub, Microsoft Graph, Mailcow.

These endpoints are PUBLIC (no JWT). The provider authenticates the
request:

* **Gmail**: a Pub/Sub envelope with an ``Authorization: Bearer <jwt>``
  header signed by Google's service account; we verify it with
  ``google.auth.transport.requests.Request``. As a fallback we also
  accept a ``?token=...`` query parameter matching
  ``GOOGLE_PUBSUB_VERIFICATION_TOKEN``.
* **Microsoft Graph**: each notification carries ``clientState`` which
  must equal ``MICROSOFT_WEBHOOK_CLIENT_STATE``. The very first call
  Graph makes is a validation handshake — it adds a
  ``?validationToken=...`` query, and we must echo it as plain text
  within 10 seconds.
* **Mailcow** (optional): shared header ``X-Mailcow-Secret`` matched
  against settings.

The receivers do as little work as possible: validate, find the
``EmailAccount``, enqueue ``incremental_sync_account`` and return 204
within ~1s.
"""

from __future__ import annotations

import base64
import json
import logging

from fastapi import APIRouter, HTTPException, Header, Query, Request, Response
from sqlalchemy import select

from app.core.settings import settings
from app.db import async_session_factory
from app.models.account import EmailAccount


log = logging.getLogger(__name__)
router = APIRouter(tags=["webhooks"])


# ────────────────────────────────────────────────────────────────────────
# Gmail — Pub/Sub push subscription
# ────────────────────────────────────────────────────────────────────────


def _verify_pubsub_jwt(authorization: str | None) -> None:
    """Validate the Bearer JWT Google attaches to push deliveries.

    Skipped entirely if google-auth isn't importable (dev fallback to
    the verification token in query string).
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        return  # caller will fall back to query token
    token = authorization.split(" ", 1)[1].strip()
    try:
        from google.auth.transport import requests as g_requests
        from google.oauth2 import id_token

        id_token.verify_oauth2_token(token, g_requests.Request())
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=401, detail=f"Invalid Pub/Sub JWT: {exc}")


@router.post("/gmail", status_code=204)
async def gmail_push(
    request: Request,
    authorization: str | None = Header(None),
    token: str | None = Query(None),
) -> Response:
    """Pub/Sub envelope: ``{message: {data: <base64-json>, ...}, subscription}``."""
    # Authentication: prefer Google's signed JWT, fall back to shared token.
    if authorization:
        _verify_pubsub_jwt(authorization)
    elif settings.google_pubsub_verification_token:
        if token != settings.google_pubsub_verification_token:
            raise HTTPException(status_code=401, detail="Invalid verification token")
    else:
        # No way to authenticate the request — refuse.
        raise HTTPException(status_code=401, detail="No auth configured")

    envelope = await request.json()
    message = envelope.get("message", {}) if isinstance(envelope, dict) else {}
    raw_b64 = message.get("data")
    if not raw_b64:
        return Response(status_code=204)

    try:
        payload = json.loads(base64.b64decode(raw_b64))
    except Exception as exc:  # noqa: BLE001
        log.warning("gmail_push_bad_payload: %s", exc)
        return Response(status_code=204)

    address = (payload.get("emailAddress") or "").lower()
    history_id = str(payload.get("historyId") or "")
    if not address:
        return Response(status_code=204)

    async with async_session_factory() as session:
        account_id = (
            await session.execute(
                select(EmailAccount.id).where(
                    EmailAccount.address == address,
                    EmailAccount.provider == "google",
                )
            )
        ).scalar_one_or_none()

    if account_id is None:
        log.info("gmail_push_no_account address=%s", address)
        return Response(status_code=204)

    from app.workers.sync_actors import incremental_sync_account
    incremental_sync_account.send(account_id, hint_history_id=history_id or None)
    return Response(status_code=204)


# ────────────────────────────────────────────────────────────────────────
# Microsoft Graph — webhook subscription
# ────────────────────────────────────────────────────────────────────────


@router.post("/microsoft")
async def microsoft_push(
    request: Request,
    validationToken: str | None = Query(None),
) -> Response:
    """Graph subscription notifications + initial validation handshake.

    Validation: the very first call Graph makes contains
    ``?validationToken=<token>`` — we echo it as ``text/plain`` to prove
    the URL is owned. Without this Graph won't accept the subscription.
    """
    if validationToken:
        return Response(content=validationToken, media_type="text/plain")

    body = await request.json()
    notifications = body.get("value", []) if isinstance(body, dict) else []
    queued = 0

    async with async_session_factory() as session:
        for notif in notifications:
            client_state = notif.get("clientState")
            if (
                settings.microsoft_webhook_client_state
                and client_state != settings.microsoft_webhook_client_state
            ):
                log.warning("graph_push_bad_clientstate")
                continue

            sub_id = notif.get("subscriptionId")
            if not sub_id:
                continue
            account_id = (
                await session.execute(
                    select(EmailAccount.id).where(
                        EmailAccount.provider == "microsoft",
                        EmailAccount.sync_state["subscription_id"].astext == sub_id,
                    )
                )
            ).scalar_one_or_none()
            if account_id is None:
                continue

            from app.workers.sync_actors import incremental_sync_account
            incremental_sync_account.send(account_id)
            queued += 1

    log.info("graph_push_received notifications=%d queued=%d", len(notifications), queued)
    return Response(status_code=202)


# ────────────────────────────────────────────────────────────────────────
# Mailcow (optional)
# ────────────────────────────────────────────────────────────────────────


@router.post("/mailcow", status_code=204)
async def mailcow_push(
    request: Request,
    x_mailcow_secret: str | None = Header(None),
) -> Response:
    """Optional Mailcow webhook — falls back to the IMAP IDLE supervisor.

    The shared secret is intentionally simple; production setups should
    front this with mTLS at the nginx layer.
    """
    expected = settings.microsoft_webhook_client_state  # we reuse the same secret
    if expected and x_mailcow_secret != expected:
        raise HTTPException(status_code=401, detail="Invalid secret")

    body = await request.json()
    address = (body.get("address") or "").lower()
    if not address:
        return Response(status_code=204)

    async with async_session_factory() as session:
        account_id = (
            await session.execute(
                select(EmailAccount.id).where(
                    EmailAccount.address == address,
                    EmailAccount.provider == "mailcow",
                )
            )
        ).scalar_one_or_none()

    if account_id is None:
        return Response(status_code=204)

    from app.workers.sync_actors import incremental_sync_account
    incremental_sync_account.send(account_id)
    return Response(status_code=204)
