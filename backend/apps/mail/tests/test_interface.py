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
from django.core.cache import cache

from apps.core.models import ServiceStatus
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


# ── ящик как источник данных для карточки сотрудника ──────────────────────
#
# Потребитель — apps.hr (форма сотрудника, вкладка «Почтовый ящик»). Главное
# в контракте не форма ответа, а поведение при выключенной аппке: «источника
# нет» вместо 503 на всю форму.

BRIEF_FIELDS = {"id", "address", "local_part", "domain", "display_name",
                "user_id", "status"}


def _mailbox(local_part: str, **kw) -> ProvisionedMailbox:
    defaults = dict(local_part=local_part, domain="htq.group",
                    address=f"{local_part}@htq.group")
    defaults.update(kw)
    return ProvisionedMailbox.objects.create(**defaults)


@pytest.mark.django_db
def test_list_mailboxes_brief_shape():
    _mailbox("i.ivanov", display_name="Иван Иванов")
    rows = interface.list_mailboxes_brief()
    assert len(rows) == 1
    assert set(rows[0]) == BRIEF_FIELDS
    assert rows[0]["address"] == "i.ivanov@htq.group"
    assert rows[0]["display_name"] == "Иван Иванов"


@pytest.mark.django_db
def test_list_mailboxes_brief_excludes_deleted():
    """Удалённая строка — надгробие, а не ящик, который можно выбрать."""
    _mailbox("alive")
    _mailbox("gone", status="deleted")
    assert [row["local_part"] for row in interface.list_mailboxes_brief()] == ["alive"]


@pytest.mark.django_db
def test_list_mailboxes_brief_unassigned_only():
    _mailbox("free")
    _mailbox("taken", user_id=42)
    rows = interface.list_mailboxes_brief(unassigned_only=True)
    assert [row["local_part"] for row in rows] == ["free"]


@pytest.mark.django_db
def test_list_mailboxes_brief_search_covers_address_and_name():
    _mailbox("s.sidorov", display_name="Семён Сидоров")
    _mailbox("other", display_name="Кто-то Другой")
    assert len(interface.list_mailboxes_brief(search="sidorov")) == 1
    assert len(interface.list_mailboxes_brief(search="Семён")) == 1


@pytest.mark.django_db
def test_get_mailbox_brief_unknown_is_none():
    assert interface.get_mailbox_brief(999999) is None


@pytest.mark.django_db
def test_get_mailbox_brief_deleted_is_none():
    mb = _mailbox("gone", status="deleted")
    assert interface.get_mailbox_brief(mb.id) is None


@pytest.mark.django_db
def test_brief_functions_degrade_quietly_when_mail_disabled():
    """Выключенная почта = «выбирать не из чего», а НЕ 503 на форму соседа.

    Отличие от остальных функций этого модуля намеренное — тот же принцип,
    что у ``provision_mailbox``.
    """
    mb = _mailbox("x")
    ServiceStatus.objects.update_or_create(app_label="mail", defaults={"enabled": False})
    cache.clear()  # флаг сервиса кэшируется на 5 секунд
    try:
        assert interface.list_mailboxes_brief() == []
        assert interface.get_mailbox_brief(mb.id) is None
    finally:
        ServiceStatus.objects.filter(app_label="mail").update(enabled=True)
        cache.clear()
