"""Паритет схемы mail-core с FastAPI-исходником (services/email/app/models/).

Порт-источники:
  * services/email/app/models/account.py::EmailAccount
  * services/email/app/models/email.py::OAuthToken
  * services/email/app/models/audit_log.py::AuditLog
  * services/email/app/models/base.py::TimestampMixin (created_at индексирован)

Решение D2 (бриф): дефолтные Django-имена таблиц — mail_emailaccount,
mail_oauthtoken, mail_auditlog. Решение 4: mailbox_id — без FK (см.
tests/test_stretch.py).
"""
import datetime

import pytest
from django.db import connection
from django.db.utils import IntegrityError

from apps.mail.models import (
    AccountProvider,
    AccountType,
    EmailAccount,
    OAuthToken,
    ProvisionedMailbox,
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


def _token(**kw):
    defaults = dict(
        user_id=1, provider="google", provider_account_id="user@example.com",
        encrypted_access_token="enc-access", expires_at=datetime.datetime.now(datetime.timezone.utc),
    )
    defaults.update(kw)
    return OAuthToken.objects.create(**defaults)


def _mailbox(**kw):
    """Реальная ProvisionedMailbox-строка — с приходом mailboxes-под-задачи
    ``EmailAccount.mailbox`` стал настоящим FK, поэтому тестам, проверяющим
    corporate-ветку EmailAccount, нужна СУЩЕСТВУЮЩАЯ строка (не голый int)."""
    defaults = dict(local_part="corp", domain="corp.example.com", address="corp-mb@corp.example.com")
    defaults.update(kw)
    return ProvisionedMailbox.objects.create(**defaults)


def _account(**kw):
    """Валидная ПО УМОЛЧАНИЮ (personal + свежий oauth_token) — ровно потому,
    что ck_email_accounts_type_consistency того требует. Тесты, которым нужна
    именно НЕВАЛИДНАЯ комбинация, передают ``oauth_token_id=None`` явно."""
    defaults = dict(
        user_id=1, type=AccountType.PERSONAL, provider=AccountProvider.GOOGLE,
        address="user@example.com",
    )
    if "oauth_token_id" not in kw and "mailbox_id" not in kw and "type" not in kw:
        defaults["oauth_token_id"] = _token().id
    defaults.update(kw)
    return defaults


# ── таблицы — дефолтные Django-имена (решение D2) ───────────────────────────

@pytest.mark.django_db
def test_default_table_names():
    with connection.cursor() as cur:
        cur.execute(
            "SELECT tablename FROM pg_tables WHERE tablename LIKE 'mail_%'"
        )
        tables = {r[0] for r in cur.fetchall()}
    assert {"mail_emailaccount", "mail_oauthtoken", "mail_auditlog"} <= tables


# ── EmailAccount ─────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_email_account_server_defaults_and_nullability():
    cols = _cols("mail_emailaccount")
    assert not cols["user_id"]["nullable"]
    assert not cols["type"]["nullable"]
    assert not cols["provider"]["nullable"]
    assert not cols["address"]["nullable"]
    assert cols["display_name"]["nullable"]
    assert cols["is_default"]["default"] is not None
    assert cols["is_active"]["default"] is not None
    assert cols["sync_state"]["default"] is not None
    assert cols["connected_at"]["default"] is not None
    assert cols["created_at"]["default"] is not None
    assert cols["updated_at"]["default"] is not None
    assert cols["mailbox_id"]["nullable"]
    assert cols["oauth_token_id"]["nullable"]


@pytest.mark.django_db
def test_email_account_field_defaults_on_create():
    # Corporate (mailbox set, никакого oauth_token) — проверяем дефолты,
    # не завязываясь на consistency-констрейнт по personal-ветке.
    mb = _mailbox(address="dflt@corp.example.com")
    acc = EmailAccount.objects.create(**_account(
        type=AccountType.CORPORATE, provider=AccountProvider.MAILCOW,
        address="corp@example.com", mailbox_id=mb.id,
    ))
    assert acc.is_default is False
    assert acc.is_active is True
    assert acc.sync_state == {}
    assert acc.connected_at is not None
    assert acc.created_at is not None
    assert acc.updated_at is not None
    assert acc.mailbox_id == mb.id
    assert acc.oauth_token_id is None


@pytest.mark.django_db
def test_email_account_unique_user_address():
    EmailAccount.objects.create(**_account())
    with pytest.raises(IntegrityError):
        EmailAccount.objects.create(**_account())


@pytest.mark.django_db
def test_email_account_unique_mailbox_id():
    mb = _mailbox(address="shared@corp.example.com")
    EmailAccount.objects.create(**_account(
        type=AccountType.CORPORATE, provider=AccountProvider.MAILCOW,
        address="a@corp.example.com", mailbox_id=mb.id,
    ))
    with pytest.raises(IntegrityError):
        EmailAccount.objects.create(**_account(
            type=AccountType.CORPORATE, provider=AccountProvider.MAILCOW,
            address="b@corp.example.com", mailbox_id=mb.id,
        ))


@pytest.mark.django_db
def test_email_account_type_check_constraint():
    with pytest.raises(IntegrityError):
        EmailAccount.objects.create(**_account(type="bogus"))


@pytest.mark.django_db
def test_email_account_provider_check_constraint():
    with pytest.raises(IntegrityError):
        EmailAccount.objects.create(**_account(provider="bogus"))


@pytest.mark.django_db
def test_email_account_type_consistency_rejects_personal_without_oauth_token():
    # personal БЕЗ oauth_token_id — нарушает ck_email_accounts_type_consistency.
    # Каждое нарушение — в СВОЁМ тесте: Postgres рвёт транзакцию на первой же
    # ошибке, второй insert в той же обёртке упал бы TransactionManagementError,
    # а не IntegrityError (см. hr/tests для того же паттерна изоляции).
    with pytest.raises(IntegrityError):
        EmailAccount.objects.create(**_account(type=AccountType.PERSONAL))


@pytest.mark.django_db
def test_email_account_type_consistency_rejects_corporate_without_mailbox():
    # corporate БЕЗ mailbox_id — тоже нарушает.
    with pytest.raises(IntegrityError):
        EmailAccount.objects.create(**_account(
            type=AccountType.CORPORATE, provider=AccountProvider.MAILCOW,
        ))


@pytest.mark.django_db(transaction=True)
def test_email_account_invalid_oauth_token_fk_raises_integrity_error():
    """FK DEFERRABLE INITIALLY DEFERRED (Django-дефолт на Postgres) — нужен
    transaction=True, иначе проверка не сработает внутри тестовой обёрточной
    транзакции (см. apps/hr/tests/test_documents_api.py, тот же паттерн)."""
    with pytest.raises(IntegrityError):
        EmailAccount.objects.create(**_account(oauth_token_id=999999))


@pytest.mark.django_db(transaction=True)
def test_email_account_invalid_mailbox_fk_raises_integrity_error():
    """Тот же DEFERRABLE-паттерн, что и оauth_token выше — mailboxes-под-
    задача (mail-mailboxes-brief.md): ``EmailAccount.mailbox`` теперь
    настоящий FK на ``ProvisionedMailbox``, несуществующий id должен
    падать IntegrityError."""
    with pytest.raises(IntegrityError):
        EmailAccount.objects.create(**_account(
            type=AccountType.CORPORATE, provider=AccountProvider.MAILCOW,
            oauth_token_id=None, mailbox_id=999999,
        ))


# ── OAuthToken ──────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_oauth_token_columns_and_indexes():
    cols = _cols("mail_oauthtoken")
    assert not cols["user_id"]["nullable"]
    assert not cols["provider"]["nullable"]
    assert not cols["provider_account_id"]["nullable"]
    assert not cols["encrypted_access_token"]["nullable"]
    assert cols["encrypted_refresh_token"]["nullable"]
    assert not cols["expires_at"]["nullable"]
    assert cols["created_at"]["default"] is not None
    assert cols["updated_at"]["default"] is not None
    assert {"user_id", "created_at"} <= _indexed_columns("mail_oauthtoken")


@pytest.mark.django_db
def test_oauth_token_is_active_default_is_client_side_only():
    """D-mail-1: исходник — ``default=True`` БЕЗ server_default (в отличие от
    EmailAccount.is_active, где server_default явный). Различие буквальное:
    вставка мимо ORM (raw SQL) НЕ получает default здесь."""
    cols = _cols("mail_oauthtoken")
    assert cols["is_active"]["default"] is None

    token = OAuthToken.objects.create(
        user_id=1, provider="google", provider_account_id="user@gmail.com",
        encrypted_access_token="enc", expires_at=datetime.datetime.now(datetime.timezone.utc),
    )
    assert token.is_active is True


# ── AuditLog(mail) ──────────────────────────────────────────────────────

@pytest.mark.django_db
def test_audit_log_columns():
    cols = _cols("mail_auditlog")
    assert cols["user_id"]["nullable"]
    assert not cols["action"]["nullable"]
    assert not cols["resource_type"]["nullable"]
    assert cols["resource_id"]["nullable"]
    assert cols["changes"]["nullable"]
    assert cols["created_at"]["default"] is not None
    assert "updated_at" not in cols  # источник не несёт updated_at
    assert {"user_id", "action", "resource_id", "correlation_id", "created_at"} <= (
        _indexed_columns("mail_auditlog")
    )
