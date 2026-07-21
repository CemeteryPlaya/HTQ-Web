"""Microsoft Graph sync — парсинг payload'ов + токен-рефреш. Порт
``services/email/app/services/sync/microsoft.py``.

Живые HTTP-опросы (``initial_backfill``/``incremental``/``register_push`` —
``/me/mailFolders/{f}/messages``, ``/messages/delta``, ``/subscriptions``)
НЕ портируются (Р2 брифа mail-messages, workers-под-задача) — переносится
только ``_ingest`` (+ ``_addresses``) — ЧИСТЫЙ маппинг уже полученного Graph
API JSON, юнит-тестируемый на записанном payload'е без сети.

``ensure_fresh_token`` переносится по той же причине, что и в
``sync/gmail.py`` — переиспользуется ``apps/mail/services/sender/graph.py``.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from apps.mail.models import EmailAccount
from apps.mail.services.crypto import crypto_service
from apps.mail.services.oauth_clients import MicrosoftOAuthClient

# Well-known folder names used in /me/mailFolders/{name} — kept for
# documentation parity; unused here (initial_backfill isn't ported).
BACKFILL_FOLDERS = ["inbox", "sentitems"]


def _addresses(recipients: list[dict] | None) -> list[dict]:
    if not recipients:
        return []
    out = []
    for r in recipients:
        addr = r.get("emailAddress") or {}
        email = (addr.get("address") or "").lower()
        if email:
            out.append({"email": email, "name": addr.get("name")})
    return out


def ingest(raw: dict, folder_name: str) -> dict:
    from apps.mail.services.sync.mapper import graph_folder_to_folder

    folder, provider_folder = graph_folder_to_folder(folder_name)
    body = raw.get("body") or {}
    body_html = body.get("content") if body.get("contentType") == "html" else None
    body_text = body.get("content") if body.get("contentType") == "text" else None

    sender_obj = (raw.get("from") or {}).get("emailAddress") or {}
    received = raw.get("receivedDateTime") or raw.get("sentDateTime")
    try:
        date = (
            datetime.fromisoformat(received.replace("Z", "+00:00"))
            if received
            else datetime.now(timezone.utc)
        )
    except Exception:
        date = datetime.now(timezone.utc)

    flag_status = ((raw.get("flag") or {}).get("flagStatus") or "").lower()

    return {
        "message_id": raw["id"],
        "thread_id": raw.get("conversationId"),
        "folder": folder,
        "provider_folder": provider_folder,
        "subject": raw.get("subject", ""),
        "snippet": raw.get("bodyPreview", ""),
        "body_html": body_html,
        "body_text": body_text,
        "sender_email": (sender_obj.get("address") or "").lower(),
        "sender_name": sender_obj.get("name"),
        "to_recipients": _addresses(raw.get("toRecipients")),
        "cc_recipients": _addresses(raw.get("ccRecipients")),
        "bcc_recipients": _addresses(raw.get("bccRecipients")),
        "is_read": bool(raw.get("isRead", False)),
        "is_flagged": flag_status == "flagged",
        "has_attachments": bool(raw.get("hasAttachments", False)),
        "date": date,
        "attachments": [],  # phase 7 (исходника) fetches via /messages/{id}/attachments
    }


def ensure_fresh_token(account: EmailAccount) -> str:
    token_row = account.oauth_token
    if token_row is None:
        raise RuntimeError(f"OAuthToken missing for account {account.id}")
    if token_row.expires_at and token_row.expires_at <= datetime.now(timezone.utc):
        if not token_row.encrypted_refresh_token:
            raise RuntimeError("Microsoft access token expired and no refresh_token")
        refresh = crypto_service.decrypt(token_row.encrypted_refresh_token)
        bundle = MicrosoftOAuthClient().refresh(refresh)
        token_row.encrypted_access_token = crypto_service.encrypt(bundle.access_token)
        if bundle.refresh_token:
            token_row.encrypted_refresh_token = crypto_service.encrypt(bundle.refresh_token)
        token_row.expires_at = datetime.now(timezone.utc) + timedelta(seconds=bundle.expires_in)
        token_row.save(update_fields=[
            "encrypted_access_token", "encrypted_refresh_token", "expires_at", "updated_at",
        ])
    return crypto_service.decrypt(token_row.encrypted_access_token)
