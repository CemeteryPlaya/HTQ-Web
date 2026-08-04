"""Двусторонняя синхронизация писем корпоративного ящика.

IMAP-соединение фейковое (тот же приём, что в test_imap_client.py), но путь
проверяется целиком: SELECT → SEARCH → FETCH → parse_eml → upsert_message →
EmailMessage в БД, курсор в EmailAccount.sync_state, и обратно — флаг \\Seen.
"""
from __future__ import annotations

import pytest
from django.test import override_settings

from apps.mail.models import (
    AccountType,
    EmailAccount,
    EmailMessage,
    ProvisionedMailbox,
)
from apps.mail.services.crypto import crypto_service
from apps.mail.services.imap_client import FetchedMessage, ImapError
from apps.mail.services.sync import imap_sync

RAW_EML = (
    b"From: Ivan Ivanov <i.ivanov@htq.group>\r\n"
    b"To: Petr <petr@htq.group>\r\n"
    b"Cc: anna@htq.group\r\n"
    b"Subject: Quarterly report\r\n"
    b"Date: Mon, 3 Aug 2026 10:00:00 +0000\r\n"
    b"Message-ID: <abc@htq.group>\r\n"
    b"Content-Type: text/plain; charset=utf-8\r\n"
    b"\r\n"
    b"Body text here\r\n"
)


# ── message_id: должен быть стабильным и обратимым в UID ─────────────────

def test_message_id_round_trip():
    mid = imap_sync.build_message_id("INBOX", 12, 940)
    assert mid == "INBOX:12:940"
    assert imap_sync.parse_message_id(mid) == ("INBOX", 12, 940)


def test_message_id_survives_folder_names_with_separators():
    mid = imap_sync.build_message_id("INBOX/Архив:2026", 12, 940)
    assert imap_sync.parse_message_id(mid) == ("INBOX/Архив:2026", 12, 940)


def test_parse_message_id_rejects_foreign_formats():
    """Gmail/Graph кладут в message_id свои идентификаторы — их нельзя
    принять за UID, иначе флаги полетят не туда."""
    assert imap_sync.parse_message_id("<abc@htq.group>") is None
    assert imap_sync.parse_message_id("") is None
    assert imap_sync.parse_message_id("18f2c1a9b0") is None


# ── фикстуры ─────────────────────────────────────────────────────────────

@pytest.fixture
def mailbox(db):
    mb = ProvisionedMailbox.objects.create(
        user_id=7, local_part="i.ivanov", domain="htq.group",
        address="i.ivanov@htq.group",
    )
    mb.encrypted_smtp_app_password = crypto_service.encrypt("S3cret!")
    mb.save(update_fields=["encrypted_smtp_app_password"])
    return mb


@pytest.fixture
def account(db, mailbox):
    return EmailAccount.objects.create(
        user_id=7, type=AccountType.CORPORATE, provider="imap",
        address="i.ivanov@htq.group", mailbox=mailbox,
    )


class _FakeImap:
    """Минимальный ImapClient-совместимый объект."""

    def __init__(self, uids=(940, 941), uidvalidity=12):
        self.uids = list(uids)
        self.uidvalidity = uidvalidity
        self.selected = []
        self.seen_pushed = []
        self.fetch_errors: set[int] = set()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return None

    def login(self, username, password):
        self.credentials = (username, password)
        return self

    def select(self, folder, readonly=True):
        self.selected.append((folder, readonly))
        return {"uidvalidity": self.uidvalidity, "uidnext": max(self.uids or [0]) + 1}

    def search_uids(self, *, since_uid=None):
        return [u for u in self.uids if not since_uid or u > since_uid]

    def fetch(self, uid):
        if uid in self.fetch_errors:
            raise ImapError("fetch blew up")
        return FetchedMessage(uid=uid, raw=RAW_EML, flags=("\\Seen",))

    def set_seen(self, folder, uids, *, seen=True):
        self.seen_pushed.append((folder, list(uids)))
        return len(uids)


@pytest.fixture
def use_imap(monkeypatch):
    def _install(fake):
        monkeypatch.setattr(
            imap_sync.ImapClient, "from_settings", classmethod(lambda cls: fake),
        )
        return fake
    return _install


SINGLE_FOLDER = dict(MAIL_SYNC_FOLDERS=["INBOX"], MAIL_SYNC_MAX_MESSAGES=200)


# ── вниз: сервер → платформа ─────────────────────────────────────────────

@pytest.mark.django_db
def test_sync_pulls_messages_into_db(account, use_imap):
    use_imap(_FakeImap())
    with override_settings(**SINGLE_FOLDER):
        result = imap_sync.sync_account(account)

    assert result.inserted == 2
    assert result.errors == []
    msg = EmailMessage.objects.get(message_id="INBOX:12:940")
    assert msg.subject == "Quarterly report"
    assert msg.sender_email == "i.ivanov@htq.group"
    assert msg.to_recipients == [{"email": "petr@htq.group", "name": "Petr"}]
    assert msg.cc_recipients == [{"email": "anna@htq.group", "name": ""}]
    assert msg.folder == "inbox"
    assert msg.user_id == 7
    assert msg.is_read is True


@pytest.mark.django_db
def test_sync_saves_cursor_in_account_sync_state(account, use_imap):
    use_imap(_FakeImap())
    with override_settings(**SINGLE_FOLDER):
        imap_sync.sync_account(account)

    account.refresh_from_db()
    assert account.sync_state["imap"]["INBOX"] == {"uidvalidity": 12, "last_uid": 941}
    assert account.last_sync_at is not None
    assert account.last_sync_error is None


@pytest.mark.django_db
def test_second_run_fetches_only_new_messages(account, use_imap):
    fake = use_imap(_FakeImap())
    with override_settings(**SINGLE_FOLDER):
        imap_sync.sync_account(account)
        account.refresh_from_db()
        fake.uids = [940, 941, 942]
        result = imap_sync.sync_account(account)

    assert result.inserted == 1
    assert EmailMessage.objects.filter(account=account).count() == 3


@pytest.mark.django_db
def test_reruns_are_idempotent(account, use_imap):
    """Тот же UID при том же UIDVALIDITY обновляет строку, а не плодит
    дубли — на этом стоит уникальный индекс (account_id, message_id)."""
    fake = use_imap(_FakeImap())
    with override_settings(**SINGLE_FOLDER):
        imap_sync.sync_account(account)
        account.refresh_from_db()
        account.sync_state = {}          # как будто курсор потеряли
        account.save(update_fields=["sync_state"])
        result = imap_sync.sync_account(account)

    assert result.updated == 2
    assert EmailMessage.objects.filter(account=account).count() == 2


@pytest.mark.django_db
def test_uidvalidity_change_resets_cursor(account, use_imap):
    """Сервер пересобрал папку — прежние UID недействительны. Без сброса
    курсора вся папка молча пропала бы из синхронизации."""
    fake = use_imap(_FakeImap())
    with override_settings(**SINGLE_FOLDER):
        imap_sync.sync_account(account)
        account.refresh_from_db()
        fake.uidvalidity = 99
        result = imap_sync.sync_account(account)

    assert result.inserted == 2          # перезабрали всё заново
    account.refresh_from_db()
    assert account.sync_state["imap"]["INBOX"]["uidvalidity"] == 99


@pytest.mark.django_db
def test_broken_folder_does_not_abort_other_folders(account, use_imap):
    class _PartlyBroken(_FakeImap):
        def select(self, folder, readonly=True):
            if folder == "Sent":
                raise ImapError("no such folder")
            return super().select(folder, readonly=readonly)

    use_imap(_PartlyBroken())
    with override_settings(MAIL_SYNC_FOLDERS=["INBOX", "Sent"], MAIL_SYNC_MAX_MESSAGES=200):
        result = imap_sync.sync_account(account)

    assert result.inserted == 2
    assert any("Sent" in e for e in result.errors)


@pytest.mark.django_db
def test_network_failure_stops_the_folder_instead_of_skipping_the_message(account, use_imap):
    """Сбой ``fetch`` — сетевой, он пройдёт при повторе. Пропустить письмо
    значило бы сдвинуть курсор за неполученное — и потерять его навсегда.
    Поэтому прогон папки обрывается, а не перескакивает."""
    fake = _FakeImap()
    fake.fetch_errors = {940}
    use_imap(fake)
    with override_settings(**SINGLE_FOLDER):
        result = imap_sync.sync_account(account)

    assert result.inserted == 0          # 941 не тронут: он ПОСЛЕ сбойного
    assert result.errors
    account.refresh_from_db()
    # Курсор не сдвинулся за 940 — следующий прогон заберёт его снова.
    assert (account.sync_state.get("imap", {}).get("INBOX") or {}).get("last_uid", 0) < 940


@pytest.mark.django_db
def test_progress_is_saved_when_the_run_breaks_midway(account, use_imap):
    """Ключевая гарантия: уже забранные письма считаются обработанными даже
    если прогон оборвался. Без неё каждый следующий прогон начинал бы папку
    заново, утыкался в то же письмо и падал — синхронизация крутилась бы
    вечно, не продвигаясь ни на одно письмо."""
    fake = _FakeImap(uids=[940, 941, 942])
    fake.fetch_errors = {942}
    use_imap(fake)
    with override_settings(**SINGLE_FOLDER):
        result = imap_sync.sync_account(account)

    assert result.inserted == 2          # 940 и 941 успели
    account.refresh_from_db()
    assert account.sync_state["imap"]["INBOX"]["last_uid"] == 941

    # Следующий прогон продолжает с 942, а не с нуля.
    fake.fetch_errors = set()
    with override_settings(**SINGLE_FOLDER):
        result = imap_sync.sync_account(account)
    assert result.inserted == 1
    assert EmailMessage.objects.filter(account=account).count() == 3


@pytest.mark.django_db
def test_socket_timeout_is_handled_like_any_network_failure(account, use_imap):
    """Таймаут сокета — ``OSError``, а НЕ ``ImapError``. Раньше он улетал
    мимо сохранения курсора, и синхронизация не двигалась вовсе."""
    class _TimingOut(_FakeImap):
        def fetch(self, uid):
            if uid == 941:
                raise TimeoutError("The read operation timed out")
            return super().fetch(uid)

    use_imap(_TimingOut())
    with override_settings(**SINGLE_FOLDER):
        result = imap_sync.sync_account(account)

    assert result.inserted == 1          # 940 сохранён
    assert result.errors
    account.refresh_from_db()
    assert account.sync_state["imap"]["INBOX"]["last_uid"] == 940


@pytest.mark.django_db
def test_unparsable_message_is_skipped_and_does_not_block_the_folder(account, use_imap, monkeypatch):
    """В отличие от сетевого сбоя разбор не починится при повторе — такое
    письмо пропускаем и двигаем курсор, иначе одно битое письмо заблокировало
    бы папку навсегда."""
    def _boom(raw):
        raise ValueError("битый MIME")
    monkeypatch.setattr(imap_sync, "parse_eml", _boom)

    use_imap(_FakeImap())
    with override_settings(**SINGLE_FOLDER):
        result = imap_sync.sync_account(account)

    assert result.inserted == 0
    assert result.errors
    account.refresh_from_db()
    # Курсор ушёл за оба письма — повторно они не заберутся.
    assert account.sync_state["imap"]["INBOX"]["last_uid"] == 941


@pytest.mark.django_db
def test_account_without_stored_password_reports_reason(db, use_imap):
    mb = ProvisionedMailbox.objects.create(
        user_id=8, local_part="no.pass", domain="htq.group", address="no.pass@htq.group",
    )
    account = EmailAccount.objects.create(
        user_id=8, type=AccountType.CORPORATE, provider="imap",
        address="no.pass@htq.group", mailbox=mb,
    )
    use_imap(_FakeImap())
    result = imap_sync.sync_account(account)

    assert result.inserted == 0
    assert "нет сохранённой учётки" in result.errors[0]
    account.refresh_from_db()
    assert "нет сохранённой учётки" in account.last_sync_error


@pytest.mark.django_db
def test_connection_failure_is_recorded_not_raised(account, use_imap):
    class _Down(_FakeImap):
        def login(self, username, password):
            raise ImapError("connection refused")

    use_imap(_Down())
    with override_settings(**SINGLE_FOLDER):
        result = imap_sync.sync_account(account)

    assert "connection refused" in result.errors[0]
    account.refresh_from_db()
    assert "connection refused" in account.last_sync_error


# ── вверх: платформа → сервер ────────────────────────────────────────────

@pytest.mark.django_db
def test_push_read_flags_sends_locally_read_messages(account, use_imap):
    fake = _FakeImap()
    use_imap(fake)
    with override_settings(**SINGLE_FOLDER):
        imap_sync.sync_account(account)

    EmailMessage.objects.filter(account=account).update(is_read=True)
    with override_settings(MAIL_SYNC_PUSH_FLAGS=True):
        pushed = imap_sync.push_read_flags(fake, account)

    assert pushed == 2
    assert fake.seen_pushed == [("INBOX", [940, 941])]


@pytest.mark.django_db
def test_push_read_flags_skips_unread(account, use_imap):
    fake = _FakeImap()
    use_imap(fake)
    with override_settings(**SINGLE_FOLDER):
        imap_sync.sync_account(account)
    EmailMessage.objects.filter(account=account).update(is_read=False)

    with override_settings(MAIL_SYNC_PUSH_FLAGS=True):
        assert imap_sync.push_read_flags(fake, account) == 0
    assert fake.seen_pushed == []


@pytest.mark.django_db
def test_push_read_flags_can_be_disabled(account, use_imap):
    fake = _FakeImap()
    use_imap(fake)
    with override_settings(**SINGLE_FOLDER):
        imap_sync.sync_account(account)
    EmailMessage.objects.filter(account=account).update(is_read=True)

    with override_settings(MAIL_SYNC_PUSH_FLAGS=False):
        assert imap_sync.push_read_flags(fake, account) == 0
    assert fake.seen_pushed == []


@pytest.mark.django_db
def test_push_read_flags_ignores_non_imap_message_ids(account, use_imap):
    """Письма OAuth-провайдеров лежат в той же таблице — их идентификаторы
    не UID, и трогать их IMAP-командой нельзя."""
    fake = _FakeImap()
    use_imap(fake)
    EmailMessage.objects.create(
        user_id=7, account=account, message_id="<gmail-thread-id>",
        sender_email="x@y.z", is_read=True, date="2026-08-03T10:00:00Z",
    )
    with override_settings(MAIL_SYNC_PUSH_FLAGS=True):
        assert imap_sync.push_read_flags(fake, account) == 0


@pytest.mark.django_db
def test_two_way_run_pulls_then_pushes(account, use_imap):
    fake = _FakeImap()
    use_imap(fake)
    with override_settings(**SINGLE_FOLDER):
        result = imap_sync.sync_account_two_way(account)

    assert result.inserted == 2
    # Письма приехали уже с \Seen, поэтому и наверх ушёл тот же набор.
    assert fake.seen_pushed == [("INBOX", [940, 941])]
