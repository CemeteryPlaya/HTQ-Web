"""Контракт /api/messenger/v1/admin/* — паритет с
``services/messenger/app/api/v1/admin.py`` (3 эндпойнта, workers/admin
под-задача, PLAN.md §6.5, последняя под-задача messenger):

  GET  /admin/rooms                       — list_all_rooms
  GET  /admin/rooms/{id}/messages         — list_messages_in_room
  POST /admin/history/archive?days=       — trigger_history_archive

Авторизация: ``require_admin`` исходника -> ``api_view(auth="jwt",
admin=True)`` — единый платформенный admin-гейт (см. apps/messenger/views.py
докстринг секции). Никакого participant-scoping — admin видит все комнаты.
"""
from __future__ import annotations

import datetime

import pytest
from django.test import Client

from apps.messenger.models import Message, Room, RoomParticipant
from apps.users.models import User, UserStatus
from htqweb.authn.jwt import issue_token_pair

BASE = "/api/messenger/v1/admin"


@pytest.fixture
def admin_user(db):
    u = User.objects.create(
        username="msg-admin", email="msg-admin@htq.test", password="x",
        status=UserStatus.ACTIVE, is_staff=True,
    )
    u.set_password("S3cret!Pass1")
    u.save()
    return u


@pytest.fixture
def plain_user(db):
    u = User.objects.create(username="msg-plain", email="msg-plain@htq.test", password="x", status=UserStatus.ACTIVE)
    u.set_password("S3cret!Pass1")
    u.save()
    return u


@pytest.fixture
def admin_auth(admin_user):
    return {"HTTP_AUTHORIZATION": f"Bearer {issue_token_pair(admin_user)['access']}"}


@pytest.fixture
def plain_auth(plain_user):
    return {"HTTP_AUTHORIZATION": f"Bearer {issue_token_pair(plain_user)['access']}"}


def _room(**kw):
    defaults = dict(room_type="group", name="Room")
    defaults.update(kw)
    return Room.objects.create(**defaults)


# ── admin gate ────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_admin_rooms_requires_auth():
    resp = Client().get(f"{BASE}/rooms")
    assert resp.status_code == 401


@pytest.mark.django_db
def test_admin_rooms_forbidden_for_plain_user(plain_auth):
    resp = Client().get(f"{BASE}/rooms", **plain_auth)
    assert resp.status_code == 403


# ── GET /admin/rooms ──────────────────────────────────────────────────────


@pytest.mark.django_db
def test_admin_list_rooms_returns_all_rooms(admin_auth):
    r1 = _room(name="A")
    r2 = _room(name="B")

    resp = Client().get(f"{BASE}/rooms", **admin_auth)

    assert resp.status_code == 200
    ids = {row["id"] for row in resp.json()}
    assert ids == {r1.id, r2.id}


@pytest.mark.django_db
def test_admin_list_rooms_respects_limit_offset(admin_auth):
    for i in range(3):
        _room(name=f"Room {i}")

    resp = Client().get(f"{BASE}/rooms?limit=1&offset=1", **admin_auth)

    assert resp.status_code == 200
    assert len(resp.json()) == 1


@pytest.mark.django_db
def test_admin_list_rooms_invalid_limit_422(admin_auth):
    resp = Client().get(f"{BASE}/rooms?limit=0", **admin_auth)
    assert resp.status_code == 422


@pytest.mark.django_db
def test_admin_list_rooms_no_slash_variant(admin_auth):
    _room()
    resp = Client().get(f"{BASE}/rooms/", **admin_auth)
    assert resp.status_code == 200


# ── GET /admin/rooms/{id}/messages ────────────────────────────────────────


@pytest.mark.django_db
def test_admin_list_room_messages_returns_all_messages(admin_auth):
    room = _room()
    m1 = Message.objects.create(room=room, sender_id=1, content="hi")
    m2 = Message.objects.create(room=room, sender_id=2, content="there")

    resp = Client().get(f"{BASE}/rooms/{room.id}/messages", **admin_auth)

    assert resp.status_code == 200
    ids = {row["id"] for row in resp.json()}
    assert ids == {str(m1.id), str(m2.id)}


@pytest.mark.django_db
def test_admin_list_room_messages_empty_room(admin_auth):
    room = _room()
    resp = Client().get(f"{BASE}/rooms/{room.id}/messages", **admin_auth)
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.django_db
def test_admin_list_room_messages_forbidden_for_plain_user(plain_auth):
    room = _room()
    resp = Client().get(f"{BASE}/rooms/{room.id}/messages", **plain_auth)
    assert resp.status_code == 403


# ── POST /admin/history/archive ───────────────────────────────────────────


@pytest.mark.django_db
def test_admin_trigger_history_archive_calls_shared_service(admin_auth, monkeypatch):
    called = {}

    def _fake_archive(days):
        called["days"] = days
        return {"rooms": 0, "files_written": 0, "messages": 0, "window_start": "x"}

    import apps.messenger.services.history_archive_service as svc
    monkeypatch.setattr(svc, "archive_recent_history", _fake_archive)

    resp = Client().post(f"{BASE}/history/archive", content_type="application/json", **admin_auth)

    assert resp.status_code == 200
    assert called["days"] == 7
    assert resp.json()["rooms"] == 0


@pytest.mark.django_db
def test_admin_trigger_history_archive_respects_days_query(admin_auth, monkeypatch):
    called = {}

    def _fake_archive(days):
        called["days"] = days
        return {"rooms": 0, "files_written": 0, "messages": 0, "window_start": "x"}

    import apps.messenger.services.history_archive_service as svc
    monkeypatch.setattr(svc, "archive_recent_history", _fake_archive)

    resp = Client().post(f"{BASE}/history/archive?days=30", content_type="application/json", **admin_auth)

    assert resp.status_code == 200
    assert called["days"] == 30


@pytest.mark.django_db
def test_admin_trigger_history_archive_invalid_days_422(admin_auth):
    resp = Client().post(f"{BASE}/history/archive?days=0", content_type="application/json", **admin_auth)
    assert resp.status_code == 422


@pytest.mark.django_db
def test_admin_trigger_history_archive_forbidden_for_plain_user(plain_auth):
    resp = Client().post(f"{BASE}/history/archive", content_type="application/json", **plain_auth)
    assert resp.status_code == 403
