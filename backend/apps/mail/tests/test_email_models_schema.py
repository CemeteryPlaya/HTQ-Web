"""Паритет схемы EmailMessage/EmailAttachment/RecipientStatus с FastAPI-
исходником (``services/email/app/models/email.py`` + миграции
``services/email/alembic/versions/{001_initial,005_email_accounts}.py``).

Решение D2 (бриф mail-messages): дефолтные Django-имена таблиц —
mail_emailmessage, mail_emailattachment, mail_recipientstatus.
"""
import datetime
import uuid

import pytest
from django.db import connection
from django.db.utils import IntegrityError

from apps.mail.models import (
    AccountProvider,
    AccountType,
    EmailAccount,
    EmailAttachment,
    EmailMessage,
    OAuthToken,
    RecipientStatus,
)


def _cols(table: str) -> dict:
    with connection.cursor() as cur:
        cur.execute(
            "SELECT column_name, is_nullable, column_default "
            "FROM information_schema.columns WHERE table_name = %s",
            [table],
        )
        return {r[0]: {"nullable": r[1] == "YES", "default": r[2]} for r in cur.fetchall()}


def _indexed_columns(table: str) -> set[str]:
    with connection.cursor() as cur:
        cur.execute("SELECT indexdef FROM pg_indexes WHERE tablename = %s", [table])
        defs = [r[0] for r in cur.fetchall()]
    cols: set[str] = set()
    for d in defs:
        inner = d[d.rfind("(") + 1 : d.rfind(")")]
        for part in inner.split(","):
            token = part.strip().strip('"').split()[0]
            cols.add(token.strip('"'))
    return cols


def _account(user_id=1, address="acct@example.com") -> EmailAccount:
    tok = OAuthToken.objects.create(
        user_id=user_id, provider="google", provider_account_id=address,
        encrypted_access_token="enc", expires_at=datetime.datetime.now(datetime.timezone.utc),
    )
    return EmailAccount.objects.create(
        user_id=user_id, type=AccountType.PERSONAL, provider=AccountProvider.GOOGLE,
        address=address, oauth_token=tok,
    )


def _message(**kw) -> EmailMessage:
    defaults = dict(
        user_id=1,
        sender_email="from@example.com",
        date=datetime.datetime.now(datetime.timezone.utc),
    )
    defaults.update(kw)
    return EmailMessage.objects.create(**defaults)


# ── таблицы — дефолтные Django-имена (решение D2) ───────────────────────────

@pytest.mark.django_db
def test_default_table_names_for_messages():
    with connection.cursor() as cur:
        cur.execute("SELECT tablename FROM pg_tables WHERE tablename LIKE 'mail_%'")
        tables = {r[0] for r in cur.fetchall()}
    assert {"mail_emailmessage", "mail_emailattachment", "mail_recipientstatus"} <= tables


# ── EmailMessage ─────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_email_message_nullability():
    cols = _cols("mail_emailmessage")
    assert not cols["user_id"]["nullable"]
    assert cols["account_id"]["nullable"]
    assert cols["message_id"]["nullable"]
    assert cols["thread_id"]["nullable"]
    assert not cols["folder"]["nullable"]
    assert not cols["provider_folder"]["nullable"]
    assert not cols["subject"]["nullable"]
    assert not cols["snippet"]["nullable"]
    assert cols["body_html"]["nullable"]
    assert cols["body_text"]["nullable"]
    assert not cols["sender_email"]["nullable"]
    assert cols["sender_name"]["nullable"]
    assert not cols["to_recipients"]["nullable"]
    assert not cols["cc_recipients"]["nullable"]
    assert not cols["bcc_recipients"]["nullable"]
    assert not cols["is_read"]["nullable"]
    assert not cols["is_flagged"]["nullable"]
    assert not cols["has_attachments"]["nullable"]
    assert not cols["date"]["nullable"]
    assert not cols["dlp_flagged"]["nullable"]


@pytest.mark.django_db
def test_email_message_client_side_defaults_have_no_server_default():
    """Исходник: ``default=`` БЕЗ ``server_default`` на folder/subject/
    snippet/to_recipients/cc_recipients/bcc_recipients/is_read/is_flagged/
    has_attachments/dlp_flagged — client-side Python-дефолт SQLAlchemy, НЕ
    DB-уровневый (тот же принцип, что ``OAuthToken.is_active`` в mail-core,
    см. test_models_schema.py::
    test_oauth_token_is_active_default_is_client_side_only)."""
    cols = _cols("mail_emailmessage")
    for name in (
        "folder", "subject", "snippet", "to_recipients", "cc_recipients",
        "bcc_recipients", "is_read", "is_flagged", "has_attachments", "dlp_flagged",
    ):
        assert cols[name]["default"] is None, f"{name} should have no DB-level default"


@pytest.mark.django_db
def test_email_message_provider_folder_has_real_server_default():
    """Исключение: ``provider_folder`` получил РЕАЛЬНЫЙ server_default=''
    при бэкфилле (``services/email/alembic/versions/005_email_accounts.py``
    ``op.add_column(..., server_default="")``), в отличие от прочих
    client-side дефолтов выше."""
    cols = _cols("mail_emailmessage")
    assert cols["provider_folder"]["default"] is not None


@pytest.mark.django_db
def test_email_message_created_updated_at_server_defaults():
    cols = _cols("mail_emailmessage")
    assert cols["created_at"]["default"] is not None
    assert cols["updated_at"]["default"] is not None


@pytest.mark.django_db
def test_email_message_indexed_columns():
    indexed = _indexed_columns("mail_emailmessage")
    assert {"user_id", "message_id", "thread_id", "created_at", "account_id"} <= indexed


@pytest.mark.django_db
def test_email_message_field_defaults_on_create():
    msg = _message()
    assert msg.folder == "inbox"
    assert msg.provider_folder == ""
    assert msg.subject == ""
    assert msg.snippet == ""
    assert msg.to_recipients == []
    assert msg.cc_recipients == []
    assert msg.bcc_recipients == []
    assert msg.is_read is False
    assert msg.is_flagged is False
    assert msg.has_attachments is False
    assert msg.dlp_flagged is False
    assert msg.account_id is None
    assert msg.created_at is not None
    assert msg.updated_at is not None


@pytest.mark.django_db
def test_email_message_account_set_null_on_account_delete():
    account = _account()
    msg = _message(account=account)
    account.delete()
    msg.refresh_from_db()
    assert msg.account_id is None


@pytest.mark.django_db
def test_email_message_unique_account_message_id_when_present():
    account = _account()
    _message(account=account, message_id="ext-1")
    with pytest.raises(IntegrityError):
        _message(account=account, message_id="ext-1")


@pytest.mark.django_db
def test_email_message_message_id_null_does_not_collide():
    """Партиционный уникальный индекс — ``WHERE message_id IS NOT NULL`` —
    несколько строк с ``message_id=None`` на одном аккаунте разрешены
    (черновики/локальные исходящие без внешнего message-id)."""
    account = _account()
    _message(account=account, message_id=None)
    _message(account=account, message_id=None)  # не должно упасть


@pytest.mark.django_db(transaction=True)
def test_email_message_invalid_account_fk_raises_integrity_error():
    """FK DEFERRABLE INITIALLY DEFERRED (Django-дефолт на Postgres) — нужен
    transaction=True, тот же паттерн, что test_models_schema.py::
    test_email_account_invalid_oauth_token_fk_raises_integrity_error."""
    with pytest.raises(IntegrityError):
        _message(account_id=999999)


# ── EmailAttachment ─────────────────────────────────────────────────────

@pytest.mark.django_db
def test_email_attachment_nullability_and_indexes():
    cols = _cols("mail_emailattachment")
    assert not cols["message_id"]["nullable"]
    assert cols["file_metadata_id"]["nullable"]
    assert not cols["filename"]["nullable"]
    assert not cols["mime_type"]["nullable"]
    assert not cols["size"]["nullable"]
    assert cols["content_id"]["nullable"]
    assert cols["created_at"]["default"] is not None
    assert cols["updated_at"]["default"] is not None
    assert {"message_id", "created_at"} <= _indexed_columns("mail_emailattachment")


@pytest.mark.django_db
def test_email_attachment_cascade_deletes_with_message():
    msg = _message()
    att = EmailAttachment.objects.create(
        message=msg, filename="a.pdf", mime_type="application/pdf", size=10,
    )
    msg.delete()
    assert not EmailAttachment.objects.filter(id=att.id).exists()


@pytest.mark.django_db
def test_email_attachment_no_direct_fk_to_file_metadata():
    """``file_metadata_id`` — голый UUID, НЕ ForeignKey (буквально как в
    исходнике — media был отдельным микросервисом; здесь сохранено ещё и
    потому, что прямой FK на apps.media_files.models.FileMetadata запрещён
    apps/core/tests/test_app_isolation.py)."""
    field = EmailAttachment._meta.get_field("file_metadata_id")
    assert field.get_internal_type() == "UUIDField"
    assert not field.is_relation


# ── RecipientStatus ──────────────────────────────────────────────────────

@pytest.mark.django_db
def test_recipient_status_defaults_and_indexes():
    msg = _message()
    rs = RecipientStatus.objects.create(message=msg, recipient_email="to@example.com")
    assert rs.status == "pending"
    assert rs.error_message is None

    cols = _cols("mail_recipientstatus")
    assert not cols["message_id"]["nullable"]
    assert not cols["recipient_email"]["nullable"]
    assert not cols["status"]["nullable"]
    assert cols["error_message"]["nullable"]
    assert {"message_id", "created_at"} <= _indexed_columns("mail_recipientstatus")


@pytest.mark.django_db
def test_recipient_status_cascade_deletes_with_message():
    msg = _message()
    rs = RecipientStatus.objects.create(message=msg, recipient_email="to@example.com")
    msg.delete()
    assert not RecipientStatus.objects.filter(id=rs.id).exists()
