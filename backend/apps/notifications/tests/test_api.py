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
                                                   "telegram": False, "telegram_linked": False}
