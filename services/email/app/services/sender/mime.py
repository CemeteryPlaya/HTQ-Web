"""Shared MIME builder used by all three senders.

Keeps the encoding rules in one place — providers differ in how they
accept the assembled message (Gmail wants base64url-encoded raw, Graph
wants a JSON tree, SMTP wants the bytes — but the body+recipients are
identical).
"""

from __future__ import annotations

import base64
from email.message import EmailMessage as MimeMessage
from email.utils import formatdate, make_msgid
from typing import Iterable

from app.models.email import EmailAttachment, EmailMessage


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

    `attachments` may be empty — Phase 7 ships without attachment upload
    in the compose path; the Phase 9 UI re-introduces it once the upload
    flow lands. Sync-side attachments are read-only and never re-sent.
    """
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

    # Attachment upload-on-send is a Phase 9 follow-up. Sync-side
    # attachments referenced via file_metadata_id stay unimplemented in
    # this iteration — the EmailAttachment row is metadata-only.
    return mime


def to_base64url(mime: MimeMessage) -> str:
    """Gmail's `users.messages.send` wants ``base64url`` of the raw MIME."""
    return base64.urlsafe_b64encode(bytes(mime)).rstrip(b"=").decode("ascii")
