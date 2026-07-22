"""Контракт apps/mail/services/sender/mime.py — буквальный (pure, stdlib)
порт services/email/app/services/sender/mime.py. Никакой сети — ни разу не
мокается, тестируется напрямую."""
import base64
import datetime

import pytest

from apps.mail.models import EmailMessage
from apps.mail.services.sender.mime import build_mime, to_base64url


def _msg(**kw) -> EmailMessage:
    defaults = dict(
        user_id=1, sender_email="from@example.com",
        date=datetime.datetime.now(datetime.timezone.utc),
    )
    defaults.update(kw)
    return EmailMessage(**defaults)  # не сохраняем — build_mime не трогает БД


@pytest.mark.django_db
def test_build_mime_sets_headers_and_recipients():
    msg = _msg(
        subject="Hi", body_text="hello",
        to_recipients=[{"email": "to@example.com", "name": "To"}],
        cc_recipients=[{"email": "cc@example.com"}],
        bcc_recipients=[{"email": "bcc@example.com"}],
    )
    mime = build_mime(msg, from_address="from@example.com", from_name="From Name")
    # stdlib email.message.EmailMessage normalises address headers on
    # access — quotes around a name with no special chars are dropped by
    # the header registry (Python's parser/serializer, not our code).
    assert mime["From"] == "From Name <from@example.com>"
    assert mime["To"] == "To <to@example.com>"
    assert mime["Cc"] == "cc@example.com"
    assert mime["Bcc"] == "bcc@example.com"
    assert mime["Subject"] == "Hi"
    assert mime.get_content().strip() == "hello"


@pytest.mark.django_db
def test_build_mime_without_name_uses_bare_address():
    msg = _msg(subject="", to_recipients=[], cc_recipients=[], bcc_recipients=[])
    mime = build_mime(msg, from_address="from@example.com", from_name=None)
    assert mime["From"] == "from@example.com"
    assert "To" not in mime


@pytest.mark.django_db
def test_build_mime_html_and_text_both_present_uses_multipart_alternative():
    msg = _msg(
        subject="s", body_text="plain", body_html="<p>html</p>",
        to_recipients=[], cc_recipients=[], bcc_recipients=[],
    )
    mime = build_mime(msg, from_address="a@example.com", from_name=None)
    assert mime.is_multipart()
    parts = [p.get_content_type() for p in mime.walk()]
    assert "text/plain" in parts
    assert "text/html" in parts


@pytest.mark.django_db
def test_build_mime_html_only():
    msg = _msg(subject="s", body_html="<p>only html</p>",
               to_recipients=[], cc_recipients=[], bcc_recipients=[])
    mime = build_mime(msg, from_address="a@example.com", from_name=None)
    assert mime.get_content_type() == "text/html"


@pytest.mark.django_db
def test_build_mime_preserves_existing_message_id():
    msg = _msg(subject="s", message_id="<custom-id@example.com>",
               to_recipients=[], cc_recipients=[], bcc_recipients=[])
    mime = build_mime(msg, from_address="a@example.com", from_name=None)
    assert mime["Message-ID"] == "<custom-id@example.com>"


def test_to_base64url_is_urlsafe_and_unpadded():
    from email.message import EmailMessage as MimeMessage

    mime = MimeMessage()
    mime["Subject"] = "s"
    mime.set_content("body")
    encoded = to_base64url(mime)
    assert "=" not in encoded
    decoded = base64.urlsafe_b64decode(encoded + "===")
    assert decoded == bytes(mime)
