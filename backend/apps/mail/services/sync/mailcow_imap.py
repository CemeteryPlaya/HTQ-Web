"""Mailcow IMAP sync — парсинг RFC 5322 писем. Порт
``services/email/app/services/sync/mailcow_imap.py``.

Живое IMAP-подключение (``_open_imap``/``_ids_in_mailbox``/``_fetch_message``
— ``aioimaplib``) НЕ портируется (Р2 брифа mail-messages, workers-под-
задача) — переносится только ``_parse_eml`` (+ ``_addresses``) — ЧИСТЫЙ
парсинг уже полученных сырых байт письма (``email.parser.BytesParser``,
stdlib, без сети), юнит-тестируемый на записанном ``.eml``-payload'е.

Нет отдельного ``ensure_fresh_token`` — Mailcow-аккаунты используют
IMAP/SMTP app-password (``ProvisionedMailbox``), не OAuth."""
from __future__ import annotations

from datetime import datetime, timezone
from email import policy
from email.parser import BytesParser
from email.utils import getaddresses, parsedate_to_datetime

# Folders synced on initial backfill — kept for documentation parity;
# unused here (initial_backfill isn't ported).
BACKFILL_MAILBOXES = ("INBOX", "Sent")


def _addresses(value: str | None) -> list[dict]:
    if not value:
        return []
    return [
        {"email": addr.lower(), "name": name}
        for name, addr in getaddresses([value])
        if addr
    ]


def parse_eml(raw_bytes: bytes) -> dict:
    """Parse an RFC 5322 message into our common message dict shape."""
    msg = BytesParser(policy=policy.default).parsebytes(raw_bytes)

    sender_addrs = _addresses(msg.get("From"))
    sender_email = sender_addrs[0]["email"] if sender_addrs else ""
    sender_name = sender_addrs[0]["name"] if sender_addrs else None

    raw_date = msg.get("Date")
    try:
        date = parsedate_to_datetime(raw_date) if raw_date else None
    except Exception:
        date = None
    if not date:
        date = datetime.now(timezone.utc)
    if date.tzinfo is None:
        date = date.replace(tzinfo=timezone.utc)

    body_html: str | None = None
    body_text: str | None = None
    attachments: list[dict] = []

    for part in msg.walk():
        if part.is_multipart():
            continue
        ctype = part.get_content_type()
        disp = (part.get_content_disposition() or "").lower()
        if disp == "attachment" or part.get_filename():
            payload = part.get_payload(decode=True) or b""
            attachments.append(
                {
                    "filename": part.get_filename() or "attachment",
                    "mime_type": ctype or "application/octet-stream",
                    "size": len(payload),
                    "content_id": part.get("Content-ID"),
                }
            )
        elif ctype == "text/html" and body_html is None:
            try:
                body_html = part.get_content()
            except Exception:
                body_html = (part.get_payload(decode=True) or b"").decode(
                    "utf-8", errors="replace"
                )
        elif ctype == "text/plain" and body_text is None:
            try:
                body_text = part.get_content()
            except Exception:
                body_text = (part.get_payload(decode=True) or b"").decode(
                    "utf-8", errors="replace"
                )

    snippet = (body_text or "")[:255]

    return {
        "thread_id": msg.get("In-Reply-To") or msg.get("References") or None,
        "subject": msg.get("Subject", "") or "",
        "snippet": snippet,
        "body_html": body_html,
        "body_text": body_text,
        "sender_email": sender_email,
        "sender_name": sender_name,
        "to_recipients": _addresses(msg.get("To")),
        "cc_recipients": _addresses(msg.get("Cc")),
        "bcc_recipients": _addresses(msg.get("Bcc")),
        "date": date,
        "attachments": attachments,
        "rfc822_message_id": msg.get("Message-ID") or "",
    }
