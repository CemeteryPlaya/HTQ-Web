"""Контракт apps/mail/services/sender/mailcow_smtp.py — порт
services/email/app/services/sender/mailcow_smtp.py, с задокументированным
ограничением: ProvisionedMailbox (mailboxes-под-задача) ещё не перенесена,
см. модуль docstring. Живая SMTP-отправка (``_send_via_smtp``) тестируется
отдельно, с фейковым ``smtplib.SMTP``, БЕЗ реальной сети."""
import datetime

import pytest

from apps.mail.models import AccountProvider, AccountType, EmailAccount, EmailMessage, OAuthToken
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
def test_send_errors_documented_no_provisioned_mailbox_model_yet():
    """Задокументированное ограничение зоны mail-messages: mailbox_id
    задан, но ProvisionedMailbox (mailboxes-под-задача) не перенесена —
    та же по духу ошибка, что вернул бы исходник для непровижининг-нутого
    ящика."""
    account = EmailAccount.objects.create(
        user_id=1, type=AccountType.CORPORATE, provider=AccountProvider.MAILCOW,
        address="corp@example.com", mailbox_id=42,
    )
    msg = _message(account=account)
    result = MailcowSmtpSender().send(account, msg)
    assert result.ok is False
    assert "no app-password" in result.error


@pytest.mark.django_db
def test_build_envelope_strips_bcc_header_but_keeps_it_in_envelope_recipients():
    account = EmailAccount.objects.create(
        user_id=1, type=AccountType.CORPORATE, provider=AccountProvider.MAILCOW,
        address="corp@example.com", mailbox_id=1, display_name="Corp",
    )
    msg = _message(account=account)
    mime, recipients = MailcowSmtpSender()._build_envelope(account, msg)
    assert "Bcc" not in mime
    assert set(recipients) == {"to@example.com", "hidden@example.com"}


@pytest.mark.django_db
def test_build_envelope_errors_would_be_no_recipients_when_all_empty():
    account = EmailAccount.objects.create(
        user_id=1, type=AccountType.CORPORATE, provider=AccountProvider.MAILCOW,
        address="corp@example.com", mailbox_id=1,
    )
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
