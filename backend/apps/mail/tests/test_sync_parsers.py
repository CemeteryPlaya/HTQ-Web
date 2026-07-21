"""Контракт парсинга провайдерских payload'ов — порт ``_ingest_message_payload``
(gmail.py), ``_ingest`` (microsoft.py), ``_parse_eml`` (mailcow_imap.py) из
services/email/app/services/sync/*.py. Записанные payload'ы, БЕЗ живой сети
(mail-messages-brief.md п.6)."""
import base64
import datetime

from apps.mail.services.sync.gmail import ingest_message_payload
from apps.mail.services.sync.mailcow_imap import parse_eml
from apps.mail.services.sync.microsoft import ingest


# ── Gmail ────────────────────────────────────────────────────────────────

def _b64url(s: str) -> str:
    return base64.urlsafe_b64encode(s.encode()).rstrip(b"=").decode("ascii")


def test_ingest_gmail_message_payload_extracts_headers_and_body():
    raw = {
        "id": "gm-1",
        "threadId": "th-1",
        "labelIds": ["INBOX"],
        "snippet": "Hello there",
        "internalDate": "1700000000000",
        "payload": {
            "headers": [
                {"name": "Subject", "value": "Hi"},
                {"name": "From", "value": "Alice <alice@example.com>"},
                {"name": "To", "value": "Bob <bob@example.com>"},
            ],
            "mimeType": "multipart/alternative",
            "parts": [
                {"mimeType": "text/plain", "body": {"data": _b64url("Hello plain")}},
                {"mimeType": "text/html", "body": {"data": _b64url("<p>Hello html</p>")}},
                {
                    "mimeType": "application/pdf",
                    "filename": "doc.pdf",
                    "body": {"data": _b64url("x"), "size": 123},
                    "headers": [{"name": "Content-ID", "value": "<cid-1>"}],
                },
            ],
        },
    }
    parsed = ingest_message_payload(raw)
    assert parsed["message_id"] == "gm-1"
    assert parsed["thread_id"] == "th-1"
    assert parsed["folder"] == "inbox"
    assert parsed["provider_folder"] == "INBOX"
    assert parsed["subject"] == "Hi"
    assert parsed["snippet"] == "Hello there"
    assert parsed["body_text"] == "Hello plain"
    assert parsed["body_html"] == "<p>Hello html</p>"
    assert parsed["sender_email"] == "alice@example.com"
    assert parsed["sender_name"] == "Alice"
    assert parsed["to_recipients"] == [{"email": "bob@example.com", "name": "Bob"}]
    assert parsed["is_read"] is True  # no UNREAD label
    assert parsed["is_flagged"] is False
    assert parsed["has_attachments"] is True
    assert parsed["attachments"] == [
        {"filename": "doc.pdf", "mime_type": "application/pdf", "size": 123, "content_id": "<cid-1>"},
    ]


def test_ingest_gmail_message_payload_unread_and_starred():
    raw = {
        "id": "gm-2",
        "labelIds": ["INBOX", "UNREAD", "STARRED"],
        "snippet": "",
        "internalDate": "1700000000000",
        "payload": {"headers": [], "mimeType": "text/plain", "body": {}},
    }
    parsed = ingest_message_payload(raw)
    assert parsed["is_read"] is False
    assert parsed["is_flagged"] is True


def test_ingest_gmail_message_payload_falls_back_to_internal_date():
    raw = {
        "id": "gm-3",
        "labelIds": ["SENT"],
        "snippet": "",
        "internalDate": "1700000000000",
        "payload": {"headers": [], "mimeType": "text/plain", "body": {}},
    }
    parsed = ingest_message_payload(raw)
    assert parsed["folder"] == "sent"
    assert parsed["date"] == datetime.datetime.fromtimestamp(1700000000, tz=datetime.timezone.utc)


# ── Microsoft Graph ──────────────────────────────────────────────────────

def test_ingest_graph_message_extracts_fields():
    raw = {
        "id": "gr-1",
        "conversationId": "conv-1",
        "subject": "Hi there",
        "bodyPreview": "preview text",
        "body": {"contentType": "html", "content": "<p>hi</p>"},
        "from": {"emailAddress": {"address": "Alice@Example.com", "name": "Alice"}},
        "toRecipients": [{"emailAddress": {"address": "bob@example.com", "name": "Bob"}}],
        "ccRecipients": [],
        "bccRecipients": [],
        "receivedDateTime": "2026-01-01T12:00:00Z",
        "isRead": False,
        "flag": {"flagStatus": "flagged"},
        "hasAttachments": False,
    }
    parsed = ingest(raw, "inbox")
    assert parsed["message_id"] == "gr-1"
    assert parsed["thread_id"] == "conv-1"
    assert parsed["folder"] == "inbox"
    assert parsed["subject"] == "Hi there"
    assert parsed["body_html"] == "<p>hi</p>"
    assert parsed["body_text"] is None
    assert parsed["sender_email"] == "alice@example.com"  # lower-cased
    assert parsed["sender_name"] == "Alice"
    assert parsed["to_recipients"] == [{"email": "bob@example.com", "name": "Bob"}]
    assert parsed["is_read"] is False
    assert parsed["is_flagged"] is True
    assert parsed["date"] == datetime.datetime(2026, 1, 1, 12, 0, tzinfo=datetime.timezone.utc)


def test_ingest_graph_message_folder_mapping():
    raw = {"id": "gr-2", "subject": "", "bodyPreview": "", "body": {},
           "from": {}, "toRecipients": [], "ccRecipients": [], "bccRecipients": []}
    parsed = ingest(raw, "sentitems")
    assert parsed["folder"] == "sent"
    assert parsed["provider_folder"] == "sentitems"


# ── Mailcow IMAP (raw RFC 5322 bytes) ────────────────────────────────────

def test_parse_eml_extracts_headers_body_and_attachment():
    raw = (
        b"From: Alice <alice@example.com>\r\n"
        b"To: Bob <bob@example.com>\r\n"
        b"Subject: Hello\r\n"
        b"Date: Mon, 01 Jan 2026 12:00:00 +0000\r\n"
        b"Message-ID: <abc@example.com>\r\n"
        b"MIME-Version: 1.0\r\n"
        b'Content-Type: multipart/mixed; boundary="BOUNDARY"\r\n'
        b"\r\n"
        b"--BOUNDARY\r\n"
        b"Content-Type: text/plain\r\n\r\n"
        b"Hello plain body\r\n"
        b"--BOUNDARY\r\n"
        b"Content-Type: application/pdf\r\n"
        b'Content-Disposition: attachment; filename="doc.pdf"\r\n\r\n'
        b"%PDF-fake-bytes\r\n"
        b"--BOUNDARY--\r\n"
    )
    parsed = parse_eml(raw)
    assert parsed["subject"] == "Hello"
    assert parsed["sender_email"] == "alice@example.com"
    assert parsed["sender_name"] == "Alice"
    assert parsed["to_recipients"] == [{"email": "bob@example.com", "name": "Bob"}]
    assert "Hello plain body" in (parsed["body_text"] or "")
    assert parsed["rfc822_message_id"] == "<abc@example.com>"
    assert len(parsed["attachments"]) == 1
    assert parsed["attachments"][0]["filename"] == "doc.pdf"
    assert parsed["attachments"][0]["mime_type"] == "application/pdf"


def test_parse_eml_defaults_date_when_missing():
    raw = b"From: a@example.com\r\nSubject: no date\r\n\r\nBody\r\n"
    parsed = parse_eml(raw)
    assert parsed["date"].tzinfo is not None
