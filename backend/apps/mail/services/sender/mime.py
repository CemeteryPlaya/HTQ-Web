"""Shared MIME builder used by all three senders — буквальный (pure,
stdlib-only) порт ``services/email/app/services/sender/mime.py``. Ни одной
строки сети — юнит-тестируется напрямую."""
from __future__ import annotations

import base64
from email.message import EmailMessage as MimeMessage
from email.utils import formatdate, make_msgid
from typing import Iterable

from apps.mail.models import EmailAttachment, EmailMessage


def _format_recipients(rs: list[dict]) -> str:
    parts = []
    for r in rs or []:
        addr = r.get("email") if isinstance(r, dict) else None
        if not addr:
            continue
        name = (r.get("name") if isinstance(r, dict) else None) or ""
        parts.append(f'"{name}" <{addr}>' if name else addr)
    return ", ".join(parts)


def build_mime(
    msg: EmailMessage,
    *,
    from_address: str,
    from_name: str | None,
    attachments: Iterable[EmailAttachment] = (),
    in_reply_to: str | None = None,
    references: list[str] | None = None,
) -> MimeMessage:
    """Assemble an RFC 5322 MIME message from our internal model.

    ``attachments`` может быть пуст — как и в исходнике (Phase 9
    upload-on-send ещё не появился; sync-side вложения read-only и никогда
    не пересылаются)."""
    mime = MimeMessage()

    display_from = f'"{from_name}" <{from_address}>' if from_name else from_address
    mime["From"] = display_from
    if msg.to_recipients:
        mime["To"] = _format_recipients(msg.to_recipients)
    if msg.cc_recipients:
        mime["Cc"] = _format_recipients(msg.cc_recipients)
    if msg.bcc_recipients:
        mime["Bcc"] = _format_recipients(msg.bcc_recipients)
    mime["Subject"] = msg.subject or ""
    mime["Date"] = formatdate(localtime=True)
    mime["Message-ID"] = msg.message_id or make_msgid()
    if in_reply_to:
        mime["In-Reply-To"] = in_reply_to
    if references:
        mime["References"] = " ".join(references)

    text = msg.body_text or ""
    html = msg.body_html or ""
    if html and text:
        mime.set_content(text)
        mime.add_alternative(html, subtype="html")
    elif html:
        mime.set_content(html, subtype="html")
    else:
        mime.set_content(text or " ")

    return mime


def to_base64url(mime: MimeMessage) -> str:
    """Gmail's `users.messages.send` wants ``base64url`` of the raw MIME."""
    return base64.urlsafe_b64encode(bytes(mime)).rstrip(b"=").decode("ascii")
