"""Tests for the mail Celery tasks (``apps/mail/tasks.py``) — webhooks+workers
sub-task (PLAN.md §6.4, last mail sub-task).

Ported from ``services/email/app/workers/{actors,sync_actors,scheduler}.py``.
Guard tests call tasks DIRECTLY (not through ``.delay(...)``), same style as
``apps/cms/tests/test_cms_tasks.py``/``apps/media_files/tests/test_media_tasks.py``.

``incremental_sync_account``'s advisory-lock contention path needs a SECOND
real Postgres session (Postgres session-level advisory locks are reentrant
within the SAME session — acquiring the same key twice from one connection
always succeeds, so the "another sync is already running" branch can only be
exercised from a genuinely different connection). That test opens a raw
``psycopg`` connection using the SAME settings Django's own test connection
holds (``django.db.connection.settings_dict`` — robust to however
pytest-django named/created the test database), not a hardcoded DB name.
"""
from __future__ import annotations

import datetime

import psycopg
import pytest
from django.db import connection as django_connection
from django.test import override_settings
from django.utils import timezone

from apps.core.models import ServiceStatus
from apps.core.services import ServiceDisabled
from apps.mail import tasks
from apps.mail.models import (
    AccountProvider,
    AccountType,
    AuditLog,
    EmailAccount,
    EmailMessage,
    OAuthToken,
    ProvisionedMailbox,
    RecipientStatus,
)
from apps.mail.services.crypto import crypto_service


def _disable_mail():
    ServiceStatus.objects.update_or_create(app_label="mail", defaults={"enabled": False})


def _mailbox(**kw) -> ProvisionedMailbox:
    defaults = dict(local_part="corp", domain="corp.example.com", address="corp-mb@corp.example.com")
    defaults.update(kw)
    return ProvisionedMailbox.objects.create(**defaults)


def _corporate_account(mailbox=None, **kw) -> EmailAccount:
    if mailbox is None:
        mailbox = _mailbox()
    defaults = dict(
        user_id=1, type=AccountType.CORPORATE, provider=AccountProvider.MAILCOW,
        address="corp@example.com", mailbox_id=mailbox.id,
    )
    defaults.update(kw)
    return EmailAccount.objects.create(**defaults)


def _personal_account(**kw) -> EmailAccount:
    tok = OAuthToken.objects.create(
        user_id=1, provider="google", provider_account_id="x@example.com",
        encrypted_access_token="enc", expires_at=timezone.now(),
    )
    defaults = dict(
        user_id=1, type=AccountType.PERSONAL, provider=AccountProvider.GOOGLE,
        address="x@example.com", oauth_token=tok,
    )
    defaults.update(kw)
    return EmailAccount.objects.create(**defaults)


def _message(**kw) -> EmailMessage:
    defaults = dict(
        user_id=1, sender_email="corp@example.com", subject="Hi", body_text="hello",
        to_recipients=[{"email": "to@example.com"}], cc_recipients=[], bcc_recipients=[],
        folder="outbox", date=timezone.now(),
    )
    defaults.update(kw)
    return EmailMessage.objects.create(**defaults)


# ── require_service guards ───────────────────────────────────────────────


@pytest.mark.django_db
def test_deliver_email_refuses_when_mail_disabled():
    _disable_mail()
    with pytest.raises(ServiceDisabled):
        tasks.deliver_email("00000000-0000-0000-0000-000000000000")


@pytest.mark.django_db
def test_incremental_sync_account_refuses_when_mail_disabled():
    _disable_mail()
    with pytest.raises(ServiceDisabled):
        tasks.incremental_sync_account(1)


@pytest.mark.django_db
def test_dlp_scan_attachment_refuses_when_mail_disabled():
    _disable_mail()
    with pytest.raises(ServiceDisabled):
        tasks.dlp_scan_attachment(1)


@pytest.mark.django_db
def test_final_purge_archived_mailboxes_refuses_when_mail_disabled():
    _disable_mail()
    with pytest.raises(ServiceDisabled):
        tasks.final_purge_archived_mailboxes()


@pytest.mark.django_db
def test_audit_log_compaction_refuses_when_mail_disabled():
    _disable_mail()
    with pytest.raises(ServiceDisabled):
        tasks.audit_log_compaction()


@pytest.mark.django_db
def test_imap_poll_fallback_refuses_when_mail_disabled():
    _disable_mail()
    with pytest.raises(ServiceDisabled):
        tasks.imap_poll_fallback()


@pytest.mark.django_db
def test_oauth_token_refresh_refuses_when_mail_disabled():
    _disable_mail()
    with pytest.raises(ServiceDisabled):
        tasks.oauth_token_refresh()


# ── deliver_email ─────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_deliver_email_not_found_is_a_noop():
    # Random UUID, no matching row — logs + returns, no exception.
    assert tasks.deliver_email("11111111-1111-1111-1111-111111111111") is None


@pytest.mark.django_db
def test_deliver_email_no_account_is_a_noop():
    msg = _message(account=None)
    assert tasks.deliver_email(str(msg.id)) is None


@pytest.mark.django_db
def test_deliver_email_inactive_account_stamps_outbox_and_raises():
    account = _corporate_account(is_active=False)
    msg = _message(account=account, folder="sent")

    with pytest.raises(RuntimeError, match="account inactive"):
        tasks.deliver_email(str(msg.id))

    msg.refresh_from_db()
    assert msg.folder == "outbox"


@pytest.mark.django_db
def test_deliver_email_success_marks_sent_and_recipients(monkeypatch):
    mb = _mailbox(encrypted_smtp_app_password=crypto_service.encrypt("s3cret-app-pass"))
    account = _corporate_account(mailbox=mb)
    msg = _message(account=account)
    RecipientStatus.objects.create(message=msg, recipient_email="to@example.com", status="pending")

    import apps.mail.services.sender.mailcow_smtp as smtp_mod
    monkeypatch.setattr(smtp_mod, "_send_via_smtp", lambda *a, **kw: None)
    # Reconcile-sync best-effort call — avoid touching the real Postgres
    # advisory-lock path in this sender-focused test.
    monkeypatch.setattr(tasks.incremental_sync_account, "delay", lambda *a, **kw: None)

    with override_settings(MAILCOW_API_URL="https://mail.example.com/api/v1"):
        tasks.deliver_email(str(msg.id))

    msg.refresh_from_db()
    assert msg.folder == "sent"
    statuses = list(msg.recipient_statuses.values_list("status", flat=True))
    assert statuses == ["sent"]


@pytest.mark.django_db
def test_deliver_email_failure_marks_bounced_and_raises(monkeypatch):
    mb = _mailbox(encrypted_smtp_app_password=crypto_service.encrypt("s3cret-app-pass"))
    account = _corporate_account(mailbox=mb)
    msg = _message(account=account)
    RecipientStatus.objects.create(message=msg, recipient_email="to@example.com", status="pending")

    import apps.mail.services.sender.mailcow_smtp as smtp_mod

    def _boom(*a, **kw):
        raise OSError("connection refused")

    monkeypatch.setattr(smtp_mod, "_send_via_smtp", _boom)

    with override_settings(MAILCOW_API_URL="https://mail.example.com/api/v1"):
        with pytest.raises(RuntimeError, match="smtp: connection refused"):
            tasks.deliver_email(str(msg.id))

    msg.refresh_from_db()
    assert msg.folder == "outbox"
    statuses = list(msg.recipient_statuses.values_list("status", "error_message"))
    assert statuses == [("bounced", "smtp: connection refused")]


# ── incremental_sync_account ────────────────────────────────────────────


@pytest.mark.django_db
def test_incremental_sync_account_missing_account_is_a_noop():
    assert tasks.incremental_sync_account(999999) is None


@pytest.mark.django_db
def test_incremental_sync_account_inactive_account_is_a_noop(caplog):
    account = _corporate_account(is_active=False)
    with caplog.at_level("INFO", logger="apps.mail.tasks"):
        tasks.incremental_sync_account(account.id)
    assert any("sync_skipped_inactive" in r.getMessage() for r in caplog.records)


@pytest.mark.django_db
def test_incremental_sync_account_active_account_runs_the_seam_and_releases_lock(caplog):
    account = _corporate_account()
    with caplog.at_level("INFO", logger="apps.mail.tasks"):
        tasks.incremental_sync_account(account.id, hint_history_id="42")
    assert any("sync_driver_not_ported" in r.getMessage() for r in caplog.records)

    # Lock was released — a second call must be able to acquire it too (same
    # session is reentrant regardless, but this also proves no exception
    # left the lock held across the `finally`).
    with caplog.at_level("INFO", logger="apps.mail.tasks"):
        tasks.incremental_sync_account(account.id)
    assert any("sync_driver_not_ported" in r.getMessage() for r in caplog.records)


@pytest.mark.django_db
def test_incremental_sync_account_skips_when_another_session_holds_the_lock(caplog):
    """Postgres session-level advisory locks are reentrant WITHIN one
    session — this can only be observed from a genuinely different
    connection, hence the raw psycopg connection here (see module
    docstring)."""
    account = _corporate_account()
    settings_dict = django_connection.settings_dict

    raw = psycopg.connect(
        host=settings_dict["HOST"], port=settings_dict["PORT"],
        dbname=settings_dict["NAME"], user=settings_dict["USER"],
        password=settings_dict["PASSWORD"], autocommit=True,
    )
    try:
        raw.execute(
            "SELECT pg_advisory_lock(%s, %s)", [tasks._ADVISORY_NAMESPACE, account.id],
        )
        with caplog.at_level("INFO", logger="apps.mail.tasks"):
            result = tasks.incremental_sync_account(account.id)
        assert result is None
        assert any("sync_skipped_locked" in r.getMessage() for r in caplog.records)
        # Never reached the driver-seam log — proves it returned early.
        assert not any("sync_driver_not_ported" in r.getMessage() for r in caplog.records)
    finally:
        raw.execute(
            "SELECT pg_advisory_unlock(%s, %s)", [tasks._ADVISORY_NAMESPACE, account.id],
        )
        raw.close()


# ── dlp_scan_attachment ──────────────────────────────────────────────────


@pytest.mark.django_db
def test_dlp_scan_attachment_is_a_logging_stub(caplog):
    with caplog.at_level("INFO", logger="apps.mail.tasks"):
        assert tasks.dlp_scan_attachment(42) is None
    assert any("dlp_scanning_attachment" in r.getMessage() for r in caplog.records)


# ── final_purge_archived_mailboxes ───────────────────────────────────────


@pytest.mark.django_db
@override_settings(MAILBOX_PURGE_AFTER_DAYS=30)
def test_final_purge_marks_old_archived_mailboxes_deleted():
    old = _mailbox(
        address="old@corp.example.com", status="archived",
        archived_at=timezone.now() - datetime.timedelta(days=31),
    )
    recent = _mailbox(
        address="recent@corp.example.com", status="archived",
        archived_at=timezone.now() - datetime.timedelta(days=5),
    )
    still_active = _mailbox(address="active@corp.example.com", status="active")

    purged = tasks.final_purge_archived_mailboxes()

    assert purged == 1
    old.refresh_from_db()
    recent.refresh_from_db()
    still_active.refresh_from_db()
    assert old.status == "deleted"
    assert old.deleted_at is not None
    assert recent.status == "archived"
    assert still_active.status == "active"


@pytest.mark.django_db
@override_settings(MAILBOX_PURGE_AFTER_DAYS=10)
def test_final_purge_grace_period_is_settings_driven():
    mb = _mailbox(
        address="edge@corp.example.com", status="archived",
        archived_at=timezone.now() - datetime.timedelta(days=11),
    )
    assert tasks.final_purge_archived_mailboxes() == 1
    mb.refresh_from_db()
    assert mb.status == "deleted"


# ── audit_log_compaction ──────────────────────────────────────────────────


@pytest.mark.django_db
@override_settings(AUDIT_LOG_RETENTION_DAYS=90)
def test_audit_log_compaction_deletes_only_stale_rows():
    stale = AuditLog.objects.create(action="login", resource_type="session")
    AuditLog.objects.filter(id=stale.id).update(
        created_at=timezone.now() - datetime.timedelta(days=91),
    )
    fresh = AuditLog.objects.create(action="login", resource_type="session")

    deleted = tasks.audit_log_compaction()

    assert deleted == 1
    assert not AuditLog.objects.filter(id=stale.id).exists()
    assert AuditLog.objects.filter(id=fresh.id).exists()


# ── imap_poll_fallback ────────────────────────────────────────────────────


@pytest.mark.django_db
def test_imap_poll_fallback_enqueues_stale_and_never_synced_mailcow_accounts(monkeypatch):
    stale = _corporate_account(
        address="stale@corp.example.com",
        last_sync_at=timezone.now() - datetime.timedelta(minutes=5),
    )
    never_synced = _corporate_account(
        mailbox=_mailbox(address="never-mb@corp.example.com"),
        address="never@corp.example.com", last_sync_at=None,
    )
    fresh = _corporate_account(
        mailbox=_mailbox(address="fresh-mb@corp.example.com"),
        address="fresh@corp.example.com", last_sync_at=timezone.now(),
    )
    personal = _personal_account(last_sync_at=None)

    enqueued = []
    monkeypatch.setattr(tasks.incremental_sync_account, "delay", lambda account_id, **kw: enqueued.append(account_id))

    count = tasks.imap_poll_fallback()

    assert count == 2
    assert set(enqueued) == {stale.id, never_synced.id}
    assert fresh.id not in enqueued
    assert personal.id not in enqueued


@pytest.mark.django_db
def test_imap_poll_fallback_no_stale_accounts_returns_zero(monkeypatch):
    _corporate_account(last_sync_at=timezone.now())
    monkeypatch.setattr(tasks.incremental_sync_account, "delay", lambda *a, **kw: pytest.fail("should not enqueue"))
    assert tasks.imap_poll_fallback() == 0


# ── oauth_token_refresh ───────────────────────────────────────────────────


@pytest.mark.django_db
def test_oauth_token_refresh_refreshes_expiring_tokens_with_refresh_token(monkeypatch):
    expiring = OAuthToken.objects.create(
        user_id=1, provider="google", provider_account_id="a@example.com",
        encrypted_access_token=crypto_service.encrypt("old-access"),
        encrypted_refresh_token=crypto_service.encrypt("refresh-tok"),
        expires_at=timezone.now() + datetime.timedelta(minutes=5),
    )
    not_expiring = OAuthToken.objects.create(
        user_id=1, provider="google", provider_account_id="b@example.com",
        encrypted_access_token=crypto_service.encrypt("still-fresh"),
        encrypted_refresh_token=crypto_service.encrypt("refresh-tok-2"),
        expires_at=timezone.now() + datetime.timedelta(hours=2),
    )
    no_refresh_token = OAuthToken.objects.create(
        user_id=1, provider="google", provider_account_id="c@example.com",
        encrypted_access_token=crypto_service.encrypt("no-refresh"),
        expires_at=timezone.now() + datetime.timedelta(minutes=1),
    )

    class _FakeBundle:
        access_token = "new-access"
        refresh_token = "new-refresh"
        expires_in = 3600

    class _FakeClient:
        def refresh(self, refresh_token):
            assert refresh_token == "refresh-tok"
            return _FakeBundle()

    import apps.mail.tasks as tasks_mod
    monkeypatch.setattr(tasks_mod, "get_oauth_client", lambda provider: _FakeClient())

    refreshed = tasks.oauth_token_refresh()

    assert refreshed == 1
    expiring.refresh_from_db()
    assert crypto_service.decrypt(expiring.encrypted_access_token) == "new-access"
    assert crypto_service.decrypt(expiring.encrypted_refresh_token) == "new-refresh"
    assert expiring.expires_at > timezone.now() + datetime.timedelta(minutes=59)

    not_expiring.refresh_from_db()
    assert crypto_service.decrypt(not_expiring.encrypted_access_token) == "still-fresh"

    no_refresh_token.refresh_from_db()
    assert crypto_service.decrypt(no_refresh_token.encrypted_access_token) == "no-refresh"


@pytest.mark.django_db
def test_oauth_token_refresh_keeps_going_after_a_provider_error(monkeypatch):
    boom = OAuthToken.objects.create(
        user_id=1, provider="google", provider_account_id="boom@example.com",
        encrypted_access_token=crypto_service.encrypt("x"),
        encrypted_refresh_token=crypto_service.encrypt("refresh"),
        expires_at=timezone.now() + datetime.timedelta(minutes=5),
    )

    class _FakeClient:
        def refresh(self, refresh_token):
            raise RuntimeError("provider unreachable")

    import apps.mail.tasks as tasks_mod
    monkeypatch.setattr(tasks_mod, "get_oauth_client", lambda provider: _FakeClient())

    # Must not raise — best-effort, logs and moves on.
    assert tasks.oauth_token_refresh() == 0
    boom.refresh_from_db()
    assert crypto_service.decrypt(boom.encrypted_access_token) == "x"
