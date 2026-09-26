"""Центр уведомлений: запись, лента компании, прочтение, каналы."""

import pytest
from django.db import transaction

from apps.notifications import interface
from apps.notifications.models import ChannelPrefs, Delivery, Notification


@pytest.fixture(autouse=True)
def _no_side_effects(monkeypatch):
    from apps.notifications.services import center

    monkeypatch.setattr(center, "_enqueue", lambda ids: None)
    monkeypatch.setattr(center, "_realtime", lambda rows: None)


def _notify(**over):
    kwargs = {"recipients": [7], "event": "bpp.request_submitted",
              "title": "Заявка ЗЗ-2026-000045 ждёт согласования",
              "url": "/bpp/requests/1", "company_slug": "htq-kz"}
    kwargs.update(over)
    return interface.notify(**kwargs)


@pytest.mark.django_db(transaction=True)
def test_notify_stores_and_lists():
    with transaction.atomic():
        ids = _notify()
    rows = interface.latest(7, company_slug="htq-kz")
    assert [row["id"] for row in rows] == ids
    assert rows[0]["title"].startswith("Заявка ЗЗ-2026-000045")


@pytest.mark.django_db
def test_feed_is_per_company_plus_common():
    _notify(company_slug="htq-kz", title="в KZ")
    _notify(company_slug="htq-uz", title="в UZ")
    _notify(company_slug=None, title="общее")
    titles = {row["title"] for row in interface.latest(7, company_slug="htq-kz")}
    assert titles == {"в KZ", "общее"}


@pytest.mark.django_db
def test_default_channels_are_bell_and_email():
    _notify()
    assert set(Delivery.objects.values_list("channel", flat=True)) == {"email"}


@pytest.mark.django_db
def test_channels_follow_prefs():
    ChannelPrefs.objects.create(user_id=7, bell=True, email=False, telegram=True)
    _notify()
    assert set(Delivery.objects.values_list("channel", flat=True)) == {"telegram"}


@pytest.mark.django_db
def test_bell_off_still_delivers_but_hides_from_feed():
    ChannelPrefs.objects.create(user_id=7, bell=False, email=True, telegram=False)
    _notify()
    assert interface.latest(7, company_slug="htq-kz") == []
    assert Notification.objects.count() == 1  # запись есть — у e-mail нужен источник


@pytest.mark.django_db
def test_read_state():
    (nid,) = _notify()
    interface.mark_read(nid, 7)
    page = interface.history(7, company_slug="htq-kz", page=1, limit=25, status="unread",
                             target_type=None)
    assert page["total"] == 0 and page["unread_total"] == 0
    interface.mark_unread(nid, 7)
    interface.mark_all_read(7, company_slug="htq-kz")
    assert interface.latest(7, company_slug="htq-kz")[0]["is_read"] is True


@pytest.mark.django_db
def test_foreign_notification_is_404():
    from django.http import Http404

    (nid,) = _notify()
    with pytest.raises(Http404):
        interface.mark_read(nid, 8)
