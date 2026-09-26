"""Доставка по каналам: письмо уходит, сбой повторяется, дубля нет."""

import pytest
from django.core import mail

from apps.notifications.models import Delivery, Notification
from apps.notifications.services import delivery
from apps.users.models import User


@pytest.fixture
def row(db):
    user = User.objects.create(username="ivanov", email="ivanov@htq.test", password="x")
    note = Notification.objects.create(recipient_id=user.pk, event="e", title="Счёт оплачен",
                                       url="/bpp/invoices/1")
    return note


@pytest.mark.django_db
def test_email_is_sent_once(row, settings):
    settings.PUBLIC_BASE_URL = "https://htq.group"
    item = Delivery.objects.create(notification=row, channel="email")
    delivery.deliver(item.id)
    delivery.deliver(item.id)  # повтор той же доставки не шлёт второе письмо
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["ivanov@htq.test"]
    assert "https://htq.group/bpp/invoices/1" in mail.outbox[0].body
    assert Delivery.objects.get(pk=item.id).state == "sent"


@pytest.mark.django_db
def test_failure_is_retryable(row, monkeypatch):
    item = Delivery.objects.create(notification=row, channel="email")

    def boom(*a, **k):
        raise OSError("smtp недоступен")

    monkeypatch.setattr(delivery, "send_mail", boom)
    with pytest.raises(delivery.RetryLater):
        delivery.deliver(item.id)
    item.refresh_from_db()
    assert (item.state, item.attempts) == ("pending", 1)
    assert "smtp" in item.last_error


@pytest.mark.django_db
def test_gives_up_after_max_attempts(row, monkeypatch):
    item = Delivery.objects.create(notification=row, channel="email",
                                   attempts=delivery.MAX_ATTEMPTS - 1)
    monkeypatch.setattr(delivery, "send_mail", lambda *a, **k: (_ for _ in ()).throw(OSError("x")))
    delivery.deliver(item.id)
    assert Delivery.objects.get(pk=item.id).state == "failed"


@pytest.mark.django_db
def test_telegram_without_link_is_skipped(row, settings):
    settings.NOTIFY_TELEGRAM_BOT_TOKEN = "t"
    item = Delivery.objects.create(notification=row, channel="telegram")
    delivery.deliver(item.id)
    assert Delivery.objects.get(pk=item.id).state == "skipped"
