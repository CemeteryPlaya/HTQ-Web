"""Контракт apps/mail/services/sender/factory.py — порт
services/email/app/services/sender/factory.py."""
import pytest

from apps.mail.services.sender.factory import get_sender
from apps.mail.services.sender.gmail import GmailSender
from apps.mail.services.sender.graph import GraphSender
from apps.mail.services.sender.mailcow_smtp import MailcowSmtpSender


def test_get_sender_google():
    sender = get_sender("google")
    assert isinstance(sender, GmailSender)
    assert sender.provider == "google"


def test_get_sender_microsoft():
    sender = get_sender("microsoft")
    assert isinstance(sender, GraphSender)
    assert sender.provider == "microsoft"


def test_get_sender_mailcow():
    sender = get_sender("mailcow")
    assert isinstance(sender, MailcowSmtpSender)
    assert sender.provider == "mailcow"


def test_get_sender_unsupported_raises_value_error():
    with pytest.raises(ValueError, match="Unsupported sender provider"):
        get_sender("bogus")
