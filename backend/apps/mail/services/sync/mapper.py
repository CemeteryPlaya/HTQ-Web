"""Map provider raw payloads → ``EmailMessage`` upsert params — порт
``services/email/app/services/sync/mapper.py``.

Django-порт ``upsert_message``: исходник делает ``INSERT ... ON CONFLICT
(account_id, message_id) DO UPDATE`` вручную (SQLAlchemy Core) с эвристикой
"``was_inserted`` = ``created_at`` моложе 5 секунд" — Django ORM даёт РОВНО
это через ``update_or_create`` (возвращает настоящий ``created: bool``, без
эвристики). Опирается на тот же партиционный уникальный индекс
``ux_email_messages_account_message`` (``apps/mail/models.py::EmailMessage.
Meta.constraints`` — порт миграции 005 исходника), что и исходное
``ON CONFLICT(index_elements=["account_id", "message_id"])``.

Redis pub/sub-уведомление ``notify_publish.publish_notify_event`` (канал
``CHANNEL_NEW_EMAIL_MESSAGE`` — task-service слушает и пишет Notification)
НЕ портируется здесь (тот же класс решений, что дропнутый dramatiq, Р2
брифа): подписчика этого канала в Django-монолите ещё нет, публикация в
пустоту не имеет наблюдаемого эффекта (тот же прецедент, что
``apps/hr/services/department_file_service.py`` — см. его докстринг).
"""
from __future__ import annotations

import datetime as _dt

from apps.mail.models import EmailAttachment, EmailMessage

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


def upsert_message(
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
    date: _dt.datetime,
) -> tuple:
    """UPSERT one message keyed on (account_id, message_id); returns
    ``(id, was_inserted)`` — тот же контракт, что и исходник."""
    if date.tzinfo is None:
        date = date.replace(tzinfo=_dt.timezone.utc)

    defaults = {
        "user_id": user_id,
        "folder": folder,
        "provider_folder": provider_folder,
        "subject": (subject or "")[:512],
        "snippet": (snippet or "")[:255],
        "body_html": body_html,
        "body_text": body_text,
        "sender_email": (sender_email or "")[:255],
        "sender_name": sender_name,
        "to_recipients": to_recipients,
        "cc_recipients": cc_recipients,
        "bcc_recipients": bcc_recipients,
        "is_read": is_read,
        "is_flagged": is_flagged,
        "has_attachments": has_attachments,
        "thread_id": thread_id,
        "date": date,
    }

    msg, created = EmailMessage.objects.update_or_create(
        account_id=account_id, message_id=message_id, defaults=defaults,
    )
    return msg.id, created


def replace_attachments(message: EmailMessage, attachments: list[dict]) -> int:
    """Replace the attachment set for a message. Returns count saved.

    Drop-and-reinsert — как в исходнике ("simpler than diffing for the
    volumes we expect"). ``file_metadata_id`` — как в исходнике, обычно
    ``None`` для этой пары полей (ни один sync-driver в исходнике не
    заполняет его — см. apps/mail/services/attachment_service.py docstring)
    — реальная загрузка байт вложения при sync тут не выполняется, ЭТО
    порт-функция metadata-only записи."""
    EmailAttachment.objects.filter(message=message).delete()

    for att in attachments:
        EmailAttachment.objects.create(
            message=message,
            file_metadata_id=att.get("file_metadata_id"),
            filename=(att["filename"] or "")[:255],
            mime_type=(att.get("mime_type") or "application/octet-stream")[:255],
            size=int(att.get("size", 0)),
            content_id=att.get("content_id"),
        )
    return len(attachments)
