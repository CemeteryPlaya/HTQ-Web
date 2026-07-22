"""Контракт apps/mail/services/sync/mapper.py — порт folder-mapping +
upsert_message/replace_attachments из services/email/app/services/sync/
mapper.py. БЕЗ живой сети (чистая логика + реальная БД для upsert)."""
import datetime

import pytest

from apps.mail.models import (
    AccountProvider,
    AccountType,
    EmailAccount,
    EmailAttachment,
    EmailMessage,
    OAuthToken,
)
from apps.mail.services.sync.mapper import (
    gmail_labels_to_folder,
    graph_folder_to_folder,
    imap_mailbox_to_folder,
    replace_attachments,
    upsert_message,
)


# ── folder mapping (pure) ────────────────────────────────────────────────

def test_gmail_labels_to_folder_known_labels():
    assert gmail_labels_to_folder(["INBOX"]) == ("inbox", "INBOX")
    assert gmail_labels_to_folder(["SENT"]) == ("sent", "SENT")
    assert gmail_labels_to_folder(["DRAFT"]) == ("drafts", "DRAFT")
    assert gmail_labels_to_folder(["TRASH"]) == ("trash", "TRASH")
    assert gmail_labels_to_folder(["SPAM"]) == ("spam", "SPAM")


def test_gmail_labels_to_folder_unknown_falls_back_to_inbox():
    folder, provider_folder = gmail_labels_to_folder(["CATEGORY_PROMOTIONS"])
    assert folder == "inbox"
    assert provider_folder == "CATEGORY_PROMOTIONS"


def test_graph_folder_to_folder_known_and_unknown():
    assert graph_folder_to_folder("sentitems") == ("sent", "sentitems")
    assert graph_folder_to_folder("JunkEmail") == ("spam", "JunkEmail")
    assert graph_folder_to_folder("CustomFolder") == ("inbox", "CustomFolder")


def test_imap_mailbox_to_folder_known_and_unknown():
    assert imap_mailbox_to_folder("INBOX") == ("inbox", "INBOX")
    assert imap_mailbox_to_folder("Sent") == ("sent", "Sent")
    assert imap_mailbox_to_folder("Trash") == ("trash", "Trash")
    assert imap_mailbox_to_folder("Junk") == ("spam", "Junk")
    assert imap_mailbox_to_folder("Archive") == ("archive", "Archive")
    assert imap_mailbox_to_folder("[Gmail]/Sent Mail") == ("sent", "[Gmail]/Sent Mail")
    assert imap_mailbox_to_folder("Weird") == ("inbox", "Weird")


# ── upsert_message / replace_attachments (real DB) ──────────────────────

@pytest.fixture
def account(db) -> EmailAccount:
    tok = OAuthToken.objects.create(
        user_id=1, provider="google", provider_account_id="acct@example.com",
        encrypted_access_token="enc", expires_at=datetime.datetime.now(datetime.timezone.utc),
    )
    return EmailAccount.objects.create(
        user_id=1, type=AccountType.PERSONAL, provider=AccountProvider.GOOGLE,
        address="acct@example.com", oauth_token=tok,
    )


def _kwargs(**overrides):
    base = dict(
        user_id=1, message_id="ext-1", thread_id="thread-1",
        folder="inbox", provider_folder="INBOX",
        subject="Hi", snippet="Hi there", body_html=None, body_text="Hi there",
        sender_email="a@example.com", sender_name="A",
        to_recipients=[{"email": "b@example.com"}], cc_recipients=[], bcc_recipients=[],
        is_read=False, is_flagged=False, has_attachments=False,
        date=datetime.datetime.now(datetime.timezone.utc),
    )
    base.update(overrides)
    return base


@pytest.mark.django_db
def test_upsert_message_inserts_then_updates_idempotently(account):
    msg_id, inserted = upsert_message(account_id=account.id, **_kwargs())
    assert inserted is True
    assert EmailMessage.objects.filter(id=msg_id, message_id="ext-1").exists()

    # Re-run with changed is_read/folder — same (account_id, message_id) key.
    msg_id2, inserted2 = upsert_message(
        account_id=account.id, **_kwargs(is_read=True, folder="archive"),
    )
    assert inserted2 is False
    assert msg_id2 == msg_id
    msg = EmailMessage.objects.get(id=msg_id)
    assert msg.is_read is True
    assert msg.folder == "archive"
    assert EmailMessage.objects.filter(account=account, message_id="ext-1").count() == 1


@pytest.mark.django_db
def test_upsert_message_truncates_long_subject_and_snippet(account):
    msg_id, _ = upsert_message(
        account_id=account.id,
        **_kwargs(subject="x" * 600, snippet="y" * 300),
    )
    msg = EmailMessage.objects.get(id=msg_id)
    assert len(msg.subject) == 512
    assert len(msg.snippet) == 255


@pytest.mark.django_db
def test_replace_attachments_drops_and_reinserts(account):
    msg_id, _ = upsert_message(account_id=account.id, **_kwargs())
    msg = EmailMessage.objects.get(id=msg_id)

    n = replace_attachments(msg, [
        {"filename": "a.pdf", "mime_type": "application/pdf", "size": 10},
        {"filename": "b.png", "mime_type": "image/png", "size": 20, "content_id": "cid1"},
    ])
    assert n == 2
    assert EmailAttachment.objects.filter(message=msg).count() == 2

    # Re-run with a different set — old rows dropped.
    n2 = replace_attachments(msg, [{"filename": "c.txt", "mime_type": "text/plain", "size": 5}])
    assert n2 == 1
    remaining = list(EmailAttachment.objects.filter(message=msg))
    assert len(remaining) == 1
    assert remaining[0].filename == "c.txt"
