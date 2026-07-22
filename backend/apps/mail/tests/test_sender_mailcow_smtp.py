"""Контракт apps/mail/services/sender/mailcow_smtp.py — порт
services/email/app/services/sender/mailcow_smtp.py.

mailboxes-под-задача (mail-mailboxes-brief.md) закрывает ограничение,
задокументированное здесь раньше: ``ProvisionedMailbox`` теперь перенесена
(apps/mail/models.py), поэтому ``MailcowSmtpSender.send`` реально резолвит
app-password через неё — та же цепочка, что и исходник (``account.mailbox_id``
-> ``ProvisionedMailbox.encrypted_smtp_app_password`` -> crypto_service.decrypt
-> ``_send_via_smtp``). Живая сеть нигде не участвует: единственный сетевой
вызов (``_send_via_smtp``) тестируется отдельно с фейковым ``smtplib.SMTP``,
а в тестах на ``send()`` он монkeypatch'ится как seam.
"""
import datetime

import pytest
from django.test import override_settings

from apps.mail.models import (
    AccountProvider,
    AccountType,
    EmailAccount,
    EmailMessage,
    OAuthToken,
    ProvisionedMailbox,
)
from apps.mail.services.crypto import crypto_service
from apps.mail.services.sender.mailcow_smtp import MailcowSmtpSender, _send_via_smtp


def _message(**kw) -> EmailMessage:
    defaults = dict(
        user_id=1, sender_email="corp@example.com", subject="Hi", body_text="hello",
        to_recipients=[{"email": "to@example.com"}],
        cc_recipients=[], bcc_recipients=[{"email": "hidden@example.com"}],
        date=datetime.datetime.now(datetime.timezone.utc),
    )
    defaults.update(kw)
    return EmailMessage.objects.create(**defaults)


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


@pytest.mark.django_db
def test_send_errors_when_no_mailbox_id():
    account = EmailAccount.objects.create(
        user_id=1, type=AccountType.PERSONAL, provider=AccountProvider.GOOGLE,
        address="x@example.com",
        oauth_token=OAuthToken.objects.create(
            user_id=1, provider="google", provider_account_id="x@example.com",
            encrypted_access_token="enc",
            expires_at=datetime.datetime.now(datetime.timezone.utc),
        ),
    )
    msg = _message(account=account)
    result = MailcowSmtpSender().send(account, msg)
    assert result.ok is False
    assert result.error == "mailcow account has no mailbox_id"


@pytest.mark.django_db
def test_send_errors_when_mailbox_has_no_app_password():
    """Порт исходника: ``mb is None or not mb.encrypted_smtp_app_password``
    -> ``SendResult(error="mailcow mailbox has no app-password")``. С реальным
    FK строка всегда существует, если ``mailbox_id`` задан — здесь бьётся
    вторая половина условия: app-password ещё не провижининг-нут (workers
    ещё не поставили его, см. mailbox_service.py докстринг)."""
    account = _corporate_account(mailbox=_mailbox(encrypted_smtp_app_password=None))
    msg = _message(account=account)
    result = MailcowSmtpSender().send(account, msg)
    assert result.ok is False
    assert result.error == "mailcow mailbox has no app-password"


@pytest.mark.django_db
def test_send_errors_when_app_password_decrypt_fails():
    mb = _mailbox(encrypted_smtp_app_password="not-valid-base64-ciphertext")
    account = _corporate_account(mailbox=mb)
    msg = _message(account=account)
    result = MailcowSmtpSender().send(account, msg)
    assert result.ok is False
    assert result.error.startswith("app-password decrypt:")


@pytest.mark.django_db
def test_send_errors_when_no_recipients():
    mb = _mailbox(encrypted_smtp_app_password=crypto_service.encrypt("app-pass"))
    account = _corporate_account(mailbox=mb)
    msg = _message(account=account, to_recipients=[], cc_recipients=[], bcc_recipients=[])
    result = MailcowSmtpSender().send(account, msg)
    assert result.ok is False
    assert result.error == "no recipients"


@pytest.mark.django_db
def test_send_success_calls_send_via_smtp_with_decrypted_password_and_returns_message_id(monkeypatch):
    mb = _mailbox(encrypted_smtp_app_password=crypto_service.encrypt("s3cret-app-pass"))
    account = _corporate_account(mailbox=mb)
    msg = _message(account=account)

    calls = []

    def _fake_send_via_smtp(mime, *, host, port, username, password, sender, recipients):
        calls.append(dict(
            host=host, port=port, username=username, password=password,
            sender=sender, recipients=recipients, message_id=mime["Message-ID"],
        ))

    import apps.mail.services.sender.mailcow_smtp as mod
    monkeypatch.setattr(mod, "_send_via_smtp", _fake_send_via_smtp)

    with override_settings(MAILCOW_API_URL="https://mail.example.com/api/v1"):
        result = MailcowSmtpSender().send(account, msg)

    assert result.ok is True
    assert len(calls) == 1
    call = calls[0]
    assert call["host"] == "mail.example.com"
    assert call["port"] == 587
    assert call["username"] == account.address
    assert call["password"] == "s3cret-app-pass"
    assert call["sender"] == account.address
    assert set(call["recipients"]) == {"to@example.com", "hidden@example.com"}
    assert result.provider_message_id == call["message_id"]


@pytest.mark.django_db
def test_send_maps_smtp_exception_to_send_result_error(monkeypatch):
    mb = _mailbox(encrypted_smtp_app_password=crypto_service.encrypt("s3cret-app-pass"))
    account = _corporate_account(mailbox=mb)
    msg = _message(account=account)

    def _raise(*a, **kw):
        raise OSError("connection refused")

    import apps.mail.services.sender.mailcow_smtp as mod
    monkeypatch.setattr(mod, "_send_via_smtp", _raise)

    result = MailcowSmtpSender().send(account, msg)
    assert result.ok is False
    assert result.error == "smtp: connection refused"


@pytest.mark.django_db
def test_build_envelope_strips_bcc_header_but_keeps_it_in_envelope_recipients():
    account = _corporate_account(display_name="Corp")
    msg = _message(account=account)
    mime, recipients = MailcowSmtpSender()._build_envelope(account, msg)
    assert "Bcc" not in mime
    assert set(recipients) == {"to@example.com", "hidden@example.com"}


@pytest.mark.django_db
def test_build_envelope_errors_would_be_no_recipients_when_all_empty():
    account = _corporate_account()
    msg = _message(account=account, to_recipients=[], cc_recipients=[], bcc_recipients=[])
    _mime, recipients = MailcowSmtpSender()._build_envelope(account, msg)
    assert recipients == []


def test_send_via_smtp_does_starttls_login_and_sendmail(monkeypatch):
    calls = []

    class _FakeSMTP:
        def __init__(self, host, port, timeout=None):
            calls.append(("connect", host, port))

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def starttls(self):
            calls.append(("starttls",))

        def login(self, username, password):
            calls.append(("login", username, password))

        def sendmail(self, sender, recipients, data):
            calls.append(("sendmail", sender, recipients, data))

    import apps.mail.services.sender.mailcow_smtp as mod
    monkeypatch.setattr(mod.smtplib, "SMTP", _FakeSMTP)

    from email.message import EmailMessage as MimeMessage
    mime = MimeMessage()
    mime.set_content("hi")

    _send_via_smtp(
        mime, host="mail.example.com", port=587, username="corp@example.com",
        password="secret", sender="corp@example.com", recipients=["to@example.com"],
    )

    assert ("connect", "mail.example.com", 587) in calls
    assert ("starttls",) in calls
    assert ("login", "corp@example.com", "secret") in calls
    assert any(c[0] == "sendmail" for c in calls)
