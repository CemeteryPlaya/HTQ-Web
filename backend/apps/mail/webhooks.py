"""Provider push receivers — Gmail Pub/Sub, Microsoft Graph, Mailcow. Port of
``services/email/app/api/v1/webhooks.py`` (3 endpoints).

These endpoints are PUBLIC (``api_view(auth=None)`` — no JWT, matches the
hr-final precedent for provider-facing receivers with no platform session).
The provider authenticates the request instead:

* **Gmail**: a Pub/Sub envelope with an ``Authorization: Bearer <jwt>``
  header signed by Google's service account; verified with
  ``google.auth.transport.requests.Request`` (``google-auth`` — appended to
  ``backend/requirements.txt``, same pin as the FastAPI source). Fallback:
  a ``?token=...`` query parameter matching
  ``settings.GOOGLE_PUBSUB_VERIFICATION_TOKEN``.
* **Microsoft Graph**: each notification carries ``clientState`` which must
  equal ``settings.MICROSOFT_WEBHOOK_CLIENT_STATE``. The very first call
  Graph makes is a validation handshake — a ``?validationToken=...`` query,
  echoed back as plain text.
* **Mailcow** (optional): shared header ``X-Mailcow-Secret``.

No rate-limiting (slowapi isn't in this Django port's dependency set — same
decision already made for hr's public endpoints, "hr-final" brief). No live
run is possible in this repo (no real Google/Microsoft/Mailcow reachable
from tests) — coverage is contract tests against recorded payload shapes
(``tests/test_webhooks.py``).

Settings (``GOOGLE_PUBSUB_VERIFICATION_TOKEN``/``MICROSOFT_WEBHOOK_CLIENT_STATE``)
are read via ``getattr(django.conf.settings, NAME, "")`` right here — same
decision as everywhere else in this app (``htqweb/settings`` is out of
``backend/apps/mail/**``'s zone); empty string by default literally mirrors
the source's own empty-string defaults.

The receivers do as little work as possible: validate, find the
``EmailAccount``, enqueue ``incremental_sync_account`` (Celery — eager in
tests, see ``htqweb/settings/test.py``) and return within ~1s.
"""
from __future__ import annotations

import base64
import json
import logging

from django.conf import settings
from django.http import HttpResponse

from htqweb.http import api_view, json_error

from .models import EmailAccount
from .tasks import incremental_sync_account

log = logging.getLogger(__name__)


def _parse_json_body(request) -> dict:
    """Best-effort JSON body parse — malformed/empty body degrades to ``{}``
    (the source's own ``request.json()`` would raise on genuinely malformed
    JSON too, but every call site below treats an empty envelope as "nothing
    to do" rather than a hard error, so a parse failure is folded into that
    same no-op path instead of a bespoke 400)."""
    try:
        return json.loads(request.body or b"{}")
    except ValueError:
        return {}


# ────────────────────────────────────────────────────────────────────────
# Gmail — Pub/Sub push subscription
# ────────────────────────────────────────────────────────────────────────


def _verify_pubsub_jwt(authorization: str) -> str | None:
    """Validate the Bearer JWT Google attaches to push deliveries.

    Returns ``None`` on success, else an error message for the 401. Caller
    already established ``authorization`` starts with ``"Bearer "``.
    """
    token = authorization.split(" ", 1)[1].strip()
    try:
        from google.auth.transport import requests as g_requests
        from google.oauth2 import id_token

        id_token.verify_oauth2_token(token, g_requests.Request())
    except Exception as exc:  # noqa: BLE001 — буквальный порт исходника
        return f"Invalid Pub/Sub JWT: {exc}"
    return None


@api_view(methods=("POST",), auth=None)
def gmail_push(request):
    """Pub/Sub envelope: ``{message: {data: <base64-json>, ...}, subscription}``."""
    authorization = request.headers.get("Authorization")
    token = request.GET.get("token")

    # Authentication: prefer Google's signed JWT, fall back to shared token.
    if authorization and authorization.lower().startswith("bearer "):
        err = _verify_pubsub_jwt(authorization)
        if err:
            return json_error(err, 401)
    elif getattr(settings, "GOOGLE_PUBSUB_VERIFICATION_TOKEN", ""):
        if token != getattr(settings, "GOOGLE_PUBSUB_VERIFICATION_TOKEN", ""):
            return json_error("Invalid verification token", 401)
    else:
        # No way to authenticate the request — refuse.
        return json_error("No auth configured", 401)

    envelope = _parse_json_body(request)
    message = envelope.get("message", {}) if isinstance(envelope, dict) else {}
    raw_b64 = message.get("data") if isinstance(message, dict) else None
    if not raw_b64:
        return HttpResponse(status=204)

    try:
        payload = json.loads(base64.b64decode(raw_b64))
    except Exception as exc:  # noqa: BLE001 — буквальный порт исходника
        log.warning("gmail_push_bad_payload: %s", exc)
        return HttpResponse(status=204)

    address = (payload.get("emailAddress") or "").lower()
    history_id = str(payload.get("historyId") or "")
    if not address:
        return HttpResponse(status=204)

    account_id = (
        EmailAccount.objects.filter(address=address, provider="google")
        .values_list("id", flat=True)
        .first()
    )
    if account_id is None:
        log.info("gmail_push_no_account address=%s", address)
        return HttpResponse(status=204)

    incremental_sync_account.delay(account_id, hint_history_id=history_id or None)
    return HttpResponse(status=204)


# ────────────────────────────────────────────────────────────────────────
# Microsoft Graph — webhook subscription
# ────────────────────────────────────────────────────────────────────────


@api_view(methods=("POST",), auth=None)
def microsoft_push(request):
    """Graph subscription notifications + initial validation handshake.

    Validation: the very first call Graph makes contains
    ``?validationToken=<token>`` — echoed back as ``text/plain`` to prove the
    URL is owned. Without this Graph won't accept the subscription.
    """
    validation_token = request.GET.get("validationToken")
    if validation_token:
        return HttpResponse(content=validation_token, content_type="text/plain")

    body = _parse_json_body(request)
    notifications = body.get("value", []) if isinstance(body, dict) else []
    expected_state = getattr(settings, "MICROSOFT_WEBHOOK_CLIENT_STATE", "")
    queued = 0

    for notif in notifications:
        client_state = notif.get("clientState")
        if expected_state and client_state != expected_state:
            log.warning("graph_push_bad_clientstate")
            continue

        sub_id = notif.get("subscriptionId")
        if not sub_id:
            continue
        account_id = (
            EmailAccount.objects.filter(
                provider="microsoft", sync_state__subscription_id=sub_id,
            )
            .values_list("id", flat=True)
            .first()
        )
        if account_id is None:
            continue

        incremental_sync_account.delay(account_id)
        queued += 1

    log.info("graph_push_received notifications=%d queued=%d", len(notifications), queued)
    return HttpResponse(status=202)


# ────────────────────────────────────────────────────────────────────────
# Mailcow (optional)
# ────────────────────────────────────────────────────────────────────────


@api_view(methods=("POST",), auth=None)
def mailcow_push(request):
    """Optional Mailcow webhook — falls back to the IMAP IDLE supervisor.

    The shared secret is intentionally simple; production setups should
    front this with mTLS at the nginx layer.

    Странность исходника (перенесена как есть, НЕ баг этого порта): the
    expected secret reuses ``settings.MICROSOFT_WEBHOOK_CLIENT_STATE`` — the
    Graph webhook's ``clientState`` setting, not a dedicated Mailcow secret
    (the source has no such setting) — see ``webhooks.py``'s
    ``mailcow_push`` docstring ("we reuse the same secret").
    """
    x_mailcow_secret = request.headers.get("X-Mailcow-Secret")
    expected = getattr(settings, "MICROSOFT_WEBHOOK_CLIENT_STATE", "")
    if expected and x_mailcow_secret != expected:
        return json_error("Invalid secret", 401)

    body = _parse_json_body(request)
    address = (body.get("address") or "").lower() if isinstance(body, dict) else ""
    if not address:
        return HttpResponse(status=204)

    account_id = (
        EmailAccount.objects.filter(address=address, provider="mailcow")
        .values_list("id", flat=True)
        .first()
    )
    if account_id is None:
        return HttpResponse(status=204)

    incremental_sync_account.delay(account_id)
    return HttpResponse(status=204)
