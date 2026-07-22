"""Tests for ``apps/mail/interface.py::archive_user_mailboxes`` — webhooks+
workers sub-task (PLAN.md §6.4). Port of ``services/email/app/workers/
user_events.py``'s ``CHANNEL_DEACTIVATED`` cascade (``_archive_personal_
accounts`` + ``_archive_corporate_mailbox``), now a direct call instead of a
Redis pub/sub subscription (Р2 — see the module's docstring).

The generic guard test (``require_service("mail")`` first, disabled ⇒
``ServiceDisabled`` before any real work) already lives in
``apps/core/tests/test_parallel_scaffold.py::test_interface_stub_guards_service_first``
— this file covers the actual cascade behaviour.
"""
from __future__ import annotations

import datetime

import pytest

from apps.mail import interface
from apps.mail.models import AccountType, EmailAccount, OAuthToken, ProvisionedMailbox


def _oauth_token(user_id: int, address: str) -> OAuthToken:
    return OAuthToken.objects.create(
        user_id=user_id, provider="google", provider_account_id=address,
        encrypted_access_token="enc",
        expires_at=datetime.datetime.now(datetime.timezone.utc),
    )


def _personal_account(user_id: int, address: str, **kw) -> EmailAccount:
    defaults = dict(
        user_id=user_id, type=AccountType.PERSONAL, provider="google",
        address=address, oauth_token=_oauth_token(user_id, address),
        is_active=True,
    )
    defaults.update(kw)
    return EmailAccount.objects.create(**defaults)


@pytest.mark.django_db
def test_archive_user_mailboxes_pauses_personal_accounts():
    acc = _personal_account(7, "u7@example.com")
    other = _personal_account(8, "u8@example.com")  # different user, untouched

    interface.archive_user_mailboxes(7)

    acc.refresh_from_db()
    other.refresh_from_db()
    assert acc.is_active is False
    assert other.is_active is True


@pytest.mark.django_db
def test_archive_user_mailboxes_leaves_already_inactive_personal_accounts_alone():
    acc = _personal_account(7, "u7@example.com", is_active=False)
    # Must not raise / must not touch updated_at unexpectedly — the source's
    # own filter (``is_active.is_(True)``) only ever selects active rows.
    interface.archive_user_mailboxes(7)
    acc.refresh_from_db()
    assert acc.is_active is False


@pytest.mark.django_db
def test_archive_user_mailboxes_archives_corporate_mailbox():
    mb = ProvisionedMailbox.objects.create(
        user_id=9, local_part="ivan", domain="corp.example.com",
        address="ivan@corp.example.com", status="active",
    )

    interface.archive_user_mailboxes(9)

    mb.refresh_from_db()
    assert mb.status == "archived"
    assert mb.archived_at is not None


@pytest.mark.django_db
def test_archive_user_mailboxes_is_idempotent_on_already_archived_mailbox():
    mb = ProvisionedMailbox.objects.create(
        user_id=9, local_part="ivan", domain="corp.example.com",
        address="ivan@corp.example.com", status="archived",
        archived_at=datetime.datetime.now(datetime.timezone.utc),
    )
    # CannotArchive from mbx_svc.archive() must be swallowed — nothing to do
    # outside the "active" state (source's own filter is status == "active").
    interface.archive_user_mailboxes(9)
    mb.refresh_from_db()
    assert mb.status == "archived"


@pytest.mark.django_db
def test_archive_user_mailboxes_ignores_users_with_no_mailbox_at_all():
    # Must not raise when the user has neither a personal account nor a
    # corporate mailbox.
    interface.archive_user_mailboxes(123456)


@pytest.mark.django_db
def test_archive_user_mailboxes_does_both_cascades_together():
    personal = _personal_account(10, "u10@example.com")
    mb = ProvisionedMailbox.objects.create(
        user_id=10, local_part="u10", domain="corp.example.com",
        address="u10@corp.example.com", status="active",
    )

    interface.archive_user_mailboxes(10)

    personal.refresh_from_db()
    mb.refresh_from_db()
    assert personal.is_active is False
    assert mb.status == "archived"
