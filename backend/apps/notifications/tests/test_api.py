"""Ручки центра — самообслуживание: только свои уведомления и свои каналы."""

import json

import pytest
from django.test import Client

from apps.access.tests.helpers import token
from apps.notifications import interface

BASE = "/api/notifications/v1"


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    from apps.notifications.services import center

    monkeypatch.setattr(center, "_enqueue", lambda ids: None)
    monkeypatch.setattr(center, "_realtime", lambda rows: None)


def _auth(user_id=7):
    return {"HTTP_AUTHORIZATION": f"Bearer {token(user_id=user_id, sub=str(user_id))}"}


@pytest.mark.django_db
def test_feed_and_mark_read():
    (nid,) = interface.notify(recipients=[7], event="e", title="Т", company_slug=None)
    feed = Client().get(f"{BASE}/notifications", **_auth()).json()
    assert [row["id"] for row in feed] == [nid]
    assert Client().post(f"{BASE}/notifications/{nid}/read", **_auth()).status_code == 204
    assert Client().post(f"{BASE}/notifications/{nid}/read", **_auth(8)).status_code == 404


@pytest.mark.django_db
def test_cannot_disable_every_channel():
    url = f"{BASE}/prefs"
    ok = Client().patch(url, data=json.dumps({"bell": True, "email": False, "telegram": False}),
                        content_type="application/json", **_auth())
    assert ok.status_code == 200
    refused = Client().patch(url, data=json.dumps({"bell": False}),
                             content_type="application/json", **_auth())
    assert refused.status_code == 422 and refused.json()["code"] == "E-NTF-01"
    assert Client().get(url, **_auth()).json() == {"bell": True, "email": False,
                                                   "telegram": False, "telegram_linked": False,
                                                   "telegram_available": False}


@pytest.mark.django_db
def test_bell_cannot_be_switched_off():
    """События задач, календаря, мессенджера, конференций и кадров приходят
    ТОЛЬКО в колокольчик (deliver=False): выключенный колокольчик при
    включённом e-mail тихо отрезал бы их все."""
    refused = Client().patch(f"{BASE}/prefs", data=json.dumps({"bell": False, "email": True}),
                             content_type="application/json", **_auth())
    assert refused.status_code == 422 and refused.json()["code"] == "E-NTF-01"
    assert Client().get(f"{BASE}/prefs", **_auth()).json()["bell"] is True


@pytest.mark.django_db
def test_telegram_needs_a_linked_chat():
    from apps.notifications.models import TelegramLink

    url = f"{BASE}/prefs"
    refused = Client().patch(url, data=json.dumps({"telegram": True}),
                             content_type="application/json", **_auth())
    assert refused.status_code == 422 and refused.json()["code"] == "E-NTF-02"
    TelegramLink.objects.create(user_id=7, chat_id="555")
    ok = Client().patch(url, data=json.dumps({"telegram": True}),
                        content_type="application/json", **_auth())
    assert ok.status_code == 200 and ok.json()["telegram"] is True


@pytest.mark.django_db
def test_malformed_id_is_404():
    """Неверный id в пути — «не найдено», а не 500 из недр ORM."""
    assert Client().post(f"{BASE}/notifications/not-a-uuid/read", **_auth()).status_code == 404


@pytest.mark.django_db
def test_bad_limit_is_422():
    response = Client().get(f"{BASE}/notifications?limit=abc", **_auth())
    assert response.status_code == 422


@pytest.mark.django_db
def test_prefs_report_telegram_availability(settings):
    settings.NOTIFY_TELEGRAM_BOT_TOKEN = "123:bot"
    settings.NOTIFY_TELEGRAM_BOT_NAME = "htq_notify_bot"
    settings.NOTIFY_TELEGRAM_WEBHOOK_SECRET = "s3cret"
    assert Client().get(f"{BASE}/prefs", **_auth()).json()["telegram_available"] is True
