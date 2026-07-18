"""Map provider raw payloads → ``EmailMessage`` UPSERT params.

Stays provider-agnostic at the call site: each driver builds a dict the
shape of ``EmailMessage.__table__.columns`` and hands it to
:func:`upsert_message` which performs an
``INSERT ... ON CONFLICT (account_id, message_id) DO UPDATE``.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.email import EmailAttachment, EmailMessage


GMAIL_LABEL_TO_FOLDER = {
    "INBOX": "inbox",
    "SENT": "sent",
    "DRAFT": "drafts",
    "TRASH": "trash",
    "SPAM": "spam",
}

GRAPH_FOLDER_TO_FOLDER = {
    "inbox": "inbox",
    "sentitems": "sent",
    "drafts": "drafts",
    "deleteditems": "trash",
    "junkemail": "spam",
    "archive": "archive",
}


def gmail_labels_to_folder(label_ids: list[str]) -> tuple[str, str]:
    """Pick a canonical folder + keep the original label as ``provider_folder``."""
    upper = [l.upper() for l in label_ids or []]
    for raw, canonical in GMAIL_LABEL_TO_FOLDER.items():
        if raw in upper:
            return canonical, raw
    return "inbox", ",".join(label_ids or [])


def graph_folder_to_folder(folder_name: str) -> tuple[str, str]:
    """Map Outlook well-known folder name to canonical."""
    canonical = GRAPH_FOLDER_TO_FOLDER.get(folder_name.lower(), "inbox")
    return canonical, folder_name


def imap_mailbox_to_folder(mailbox: str) -> tuple[str, str]:
    """Map an IMAP mailbox name to canonical folder."""
    name = mailbox.upper()
    if "INBOX" in name and "/" not in mailbox:
        return "inbox", mailbox
    if "SENT" in name:
        return "sent", mailbox
    if "DRAFT" in name:
        return "drafts", mailbox
    if "TRASH" in name or "DELETED" in name:
        return "trash", mailbox
    if "SPAM" in name or "JUNK" in name:
        return "spam", mailbox
    if "ARCHIVE" in name:
        return "archive", mailbox
    return "inbox", mailbox


async def upsert_message(
    session: AsyncSession,
    *,
    user_id: int,
    account_id: int,
    message_id: str,
    thread_id: str | None,
    folder: str,
    provider_folder: str,
    subject: str,
    snippet: str,
    body_html: str | None,
    body_text: str | None,
    sender_email: str,
    sender_name: str | None,
    to_recipients: list[dict],
    cc_recipients: list[dict],
    bcc_recipients: list[dict],
    is_read: bool,
    is_flagged: bool,
    has_attachments: bool,
    date: datetime,
) -> tuple[uuid.UUID, bool]:
    """UPSERT one message; returns ``(id, was_inserted)``."""
    payload: dict[str, Any] = {
        "id": uuid.uuid4(),
        "user_id": user_id,
        "account_id": account_id,
        "message_id": message_id,
        "thread_id": thread_id,
        "folder": folder,
        "provider_folder": provider_folder,
        "subject": subject[:512] if subject else "",
        "snippet": (snippet or "")[:255],
        "body_html": body_html,
        "body_text": body_text,
        "sender_email": sender_email[:255] if sender_email else "",
        "sender_name": sender_name,
        "to_recipients": to_recipients,
        "cc_recipients": cc_recipients,
        "bcc_recipients": bcc_recipients,
        "is_read": is_read,
        "is_flagged": is_flagged,
        "has_attachments": has_attachments,
        "date": date if date.tzinfo else date.replace(tzinfo=timezone.utc),
        "dlp_flagged": False,
    }

    stmt = (
        pg_insert(EmailMessage)
        .values(**payload)
        .on_conflict_do_update(
            index_elements=["account_id", "message_id"],
            set_={
                "folder": payload["folder"],
                "provider_folder": payload["provider_folder"],
                "is_read": payload["is_read"],
                "is_flagged": payload["is_flagged"],
                "has_attachments": payload["has_attachments"],
                "thread_id": payload["thread_id"],
            },
        )
        .returning(EmailMessage.id, EmailMessage.created_at)
    )
    result = await session.execute(stmt)
    row = result.one()
    # `was_inserted` heuristic: created_at within last 5 seconds.
    inserted = (datetime.now(timezone.utc) - row.created_at).total_seconds() < 5

    # Fan out a notify event for fresh inbox messages so task-service can
    # write a Notification row. Skipped for already-read / non-inbox /
    # already-known messages so the user doesn't get spammed when the
    # sync backfills history.
    if inserted and folder == "inbox" and not is_read:
        try:
            from app.services.notify_publish import (
                CHANNEL_NEW_EMAIL_MESSAGE,
                publish_notify_event,
            )
            await publish_notify_event(
                CHANNEL_NEW_EMAIL_MESSAGE,
                {
                    "message_uuid": str(row.id),
                    "user_id": user_id,
                    "account_id": account_id,
                    "subject": subject or "(без темы)",
                    "sender_email": sender_email or "",
                    "sender_name": sender_name or "",
                    "snippet": (snippet or "")[:200],
                },
            )
        except Exception:  # noqa: BLE001
            # Publish failures must not poison the sync transaction.
            pass

    return row.id, inserted


async def replace_attachments(
    session: AsyncSession,
    message_uuid: uuid.UUID,
    attachments: list[dict],
) -> int:
    """Replace the attachment set for a message. Returns count saved."""
    # Drop and re-insert is simpler than diffing for the volumes we expect
    # (typically ≤ 10 attachments per message).
    existing = (
        await session.execute(
            select(EmailAttachment).where(EmailAttachment.message_id == message_uuid)
        )
    ).scalars().all()
    for att in existing:
        await session.delete(att)

    for att in attachments:
        session.add(
            EmailAttachment(
                id=uuid.uuid4(),
                message_id=message_uuid,
                file_metadata_id=att.get("file_metadata_id"),
                filename=att["filename"][:255],
                mime_type=att.get("mime_type", "application/octet-stream")[:255],
                size=int(att.get("size", 0)),
                content_id=att.get("content_id"),
            )
        )
    return len(attachments)
