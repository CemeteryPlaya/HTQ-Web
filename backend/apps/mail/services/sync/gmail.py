"""Gmail sync — парсинг payload'ов + токен-рефреш. Порт
``services/email/app/services/sync/gmail.py``.

Живые HTTP-опросы (``initial_backfill``/``incremental``/``register_push`` —
``users.messages.list``/``users.messages.get``/``users.history.list``/
``users.watch``) НЕ портируются (Р2 брифа mail-messages, workers-под-задача)
— переносится только ``_ingest_message_payload`` (+ вспомогательные
``_walk_parts``/``_parse_addresses``) — ЧИСТЫЙ маппинг уже полученного
Gmail API JSON в параметры ``mapper.upsert_message``, юнит-тестируемый на
записанном payload'е без сети.

``ensure_fresh_token`` — единственная функция здесь, которая ходит в сеть
(refresh access_token у Google, ТОЛЬКО если он истёк) — портируется, потому
что переиспользуется ``apps/mail/services/sender/gmail.py`` (тот же путь,
что в исходнике: ``sender/gmail.py`` импортирует ``_ensure_fresh_token``
именно из ``sync/gmail.py``). SYNC (не asyncio) — Django-вьюхи синхронные,
тот же принцип, что ``apps/mail/services/oauth_clients.py``.
"""
from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
from email.utils import getaddresses, parsedate_to_datetime

from apps.mail.models import EmailAccount
from apps.mail.services.crypto import crypto_service
from apps.mail.services.oauth_clients import GoogleOAuthClient

# Folders synced on backfill — kept for documentation parity with the
# source (unused here since initial_backfill itself isn't ported).
BACKFILL_LABELS = ["INBOX", "SENT"]


def _b64url_decode(data: str) -> bytes:
    """Gmail uses URL-safe base64 without padding."""
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


def _parse_addresses(value: str | None) -> list[dict]:
    if not value:
        return []
    return [
        {"email": addr.lower(), "name": name}
        for name, addr in getaddresses([value])
        if addr
    ]


def _walk_parts(payload: dict) -> tuple[str | None, str | None, list[dict]]:
    """Returns (body_html, body_text, attachments)."""
    body_html: str | None = None
    body_text: str | None = None
    attachments: list[dict] = []

    def visit(part: dict) -> None:
        nonlocal body_html, body_text
        mime = part.get("mimeType", "")
        body = part.get("body", {})
        filename = part.get("filename") or ""
        data = body.get("data")

        if filename:
            attachments.append(
                {
                    "filename": filename,
                    "mime_type": mime or "application/octet-stream",
                    "size": int(body.get("size", 0)),
                    "content_id": next(
                        (
                            h["value"]
                            for h in part.get("headers", [])
                            if h.get("name", "").lower() == "content-id"
                        ),
                        None,
                    ),
                }
            )
        elif mime == "text/html" and data and body_html is None:
            body_html = _b64url_decode(data).decode("utf-8", errors="replace")
        elif mime == "text/plain" and data and body_text is None:
            body_text = _b64url_decode(data).decode("utf-8", errors="replace")

        for sub in part.get("parts", []) or []:
            visit(sub)

    visit(payload)
    return body_html, body_text, attachments


def ingest_message_payload(raw: dict) -> dict:
    """Convert a Gmail API message payload to mapper.upsert_message kwargs."""
    payload = raw.get("payload", {})
    headers = {h["name"].lower(): h["value"] for h in payload.get("headers", [])}

    folder, provider_folder = _folder_from_labels(raw.get("labelIds", []))

    body_html, body_text, attachments = _walk_parts(payload)

    raw_date = headers.get("date")
    try:
        date = parsedate_to_datetime(raw_date) if raw_date else None
    except Exception:
        date = None
    if not date:
        # `internalDate` is ms since epoch.
        ts = int(raw.get("internalDate", 0)) / 1000
        date = datetime.fromtimestamp(ts, tz=timezone.utc)

    sender_email = ""
    sender_name = None
    from_addrs = _parse_addresses(headers.get("from"))
    if from_addrs:
        sender_email = from_addrs[0]["email"]
        sender_name = from_addrs[0]["name"] or None

    return {
        "message_id": raw["id"],
        "thread_id": raw.get("threadId"),
        "folder": folder,
        "provider_folder": provider_folder,
        "subject": headers.get("subject", ""),
        "snippet": raw.get("snippet", ""),
        "body_html": body_html,
        "body_text": body_text,
        "sender_email": sender_email,
        "sender_name": sender_name,
        "to_recipients": _parse_addresses(headers.get("to")),
        "cc_recipients": _parse_addresses(headers.get("cc")),
        "bcc_recipients": _parse_addresses(headers.get("bcc")),
        "is_read": "UNREAD" not in (raw.get("labelIds") or []),
        "is_flagged": "STARRED" in (raw.get("labelIds") or []),
        "has_attachments": bool(attachments),
        "date": date,
        "attachments": attachments,
    }


def _folder_from_labels(label_ids: list[str]) -> tuple[str, str]:
    from apps.mail.services.sync.mapper import gmail_labels_to_folder

    return gmail_labels_to_folder(label_ids)


def ensure_fresh_token(account: EmailAccount) -> str:
    """Decrypt access token; refresh via Google if expired. Returns the
    decrypted (fresh) access token; persists a refreshed token on
    ``account.oauth_token``."""
    token_row = account.oauth_token
    if token_row is None:
        raise RuntimeError(f"OAuthToken missing for account {account.id}")

    if token_row.expires_at and token_row.expires_at <= datetime.now(timezone.utc):
        if not token_row.encrypted_refresh_token:
            raise RuntimeError("Access token expired and no refresh_token stored")
        refresh = crypto_service.decrypt(token_row.encrypted_refresh_token)
        bundle = GoogleOAuthClient().refresh(refresh)
        token_row.encrypted_access_token = crypto_service.encrypt(bundle.access_token)
        if bundle.refresh_token:
            token_row.encrypted_refresh_token = crypto_service.encrypt(bundle.refresh_token)
        token_row.expires_at = datetime.now(timezone.utc) + timedelta(seconds=bundle.expires_in)
        token_row.save(update_fields=[
            "encrypted_access_token", "encrypted_refresh_token", "expires_at", "updated_at",
        ])

    return crypto_service.decrypt(token_row.encrypted_access_token)
