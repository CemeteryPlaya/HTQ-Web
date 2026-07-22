"""Контракт /api/messenger/v1/rooms/* — паритет с
``services/messenger/app/api/v1/rooms.py`` (4 эндпойнта):

  GET    /rooms/                — list_user_rooms
  POST   /rooms/                — create_room (201, ВСЕГДА — и на новую, и
                                   на найденную существующую direct-комнату)
  GET    /rooms/{id}            — get_room
  PATCH  /rooms/{id}            — update_room (только group + admin-участник)

Авторизация (бриф п.3): обычный JWT-пользователь (``get_current_user``
исходника) -> ``auth="jwt"``. СТРОГИЙ participant-scoping: комнату видит
только её участник (``RoomParticipant``), буквальный порядок проверок
исходника — «не участник» проверяется РАНЬШЕ существования комнаты (см.
``apps/messenger/services/messenger_service.py::get_room``).

Пользователи — реальные ``apps.users.models.User`` (как в hr/mail-тестах),
``apps.users.interface.get_users_brief`` резолвит настоящие строки — без
моков, ближе к контракту.
"""
from __future__ import annotations

import pytest
from django.test import Client

from apps.messenger.models import Room, RoomParticipant
from apps.users.models import User, UserStatus
from htqweb.authn.jwt import issue_token_pair

BASE = "/api/messenger/v1/rooms"


@pytest.fixture
def user(db):
    u = User.objects.create(username="msg-user", email="msg-user@htq.test", password="x", status=UserStatus.ACTIVE)
    u.set_password("S3cret!Pass1")
    u.save()
    return u


@pytest.fixture
def other_user(db):
    u = User.objects.create(username="msg-other", email="msg-other@htq.test", password="x", status=UserStatus.ACTIVE)
    u.set_password("S3cret!Pass1")
    u.save()
    return u


@pytest.fixture
def third_user(db):
    u = User.objects.create(username="msg-third", email="msg-third@htq.test", password="x", status=UserStatus.ACTIVE)
    u.set_password("S3cret!Pass1")
    u.save()
    return u


@pytest.fixture
def auth(user):
    return {"HTTP_AUTHORIZATION": f"Bearer {issue_token_pair(user)['access']}"}


@pytest.fixture
def other_auth(other_user):
    return {"HTTP_AUTHORIZATION": f"Bearer {issue_token_pair(other_user)['access']}"}


def _direct_room(a_id, b_id):
    room = Room.objects.create(room_type="direct")
    RoomParticipant.objects.create(room=room, user_id=a_id, role="admin")
    RoomParticipant.objects.create(room=room, user_id=b_id, role="member")
    return room


def _group_room(admin_id, *member_ids, name="Group"):
    room = Room.objects.create(room_type="group", name=name)
    RoomParticipant.objects.create(room=room, user_id=admin_id, role="admin")
    for uid in member_ids:
        RoomParticipant.objects.create(room=room, user_id=uid, role="member")
    return room


# ── auth ─────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_requires_jwt():
    assert Client().get(f"{BASE}/").status_code == 401


# ── POST /rooms/ ─────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_create_direct_room(user, other_user, auth):
    resp = Client().post(
        f"{BASE}/", data={"room_type": "direct", "participant_ids": [other_user.id]},
        content_type="application/json", **auth,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["room_type"] == "direct"
    user_ids = {p["user_id"] for p in body["participants"]}
    assert user_ids == {user.id, other_user.id}
    creator = next(p for p in body["participants"] if p["user_id"] == user.id)
    assert creator["role"] == "admin"
    other = next(p for p in body["participants"] if p["user_id"] == other_user.id)
    assert other["role"] == "member"
    assert body["last_message"] is None


@pytest.mark.django_db
def test_create_direct_room_returns_existing_pair_idempotently(user, other_user, auth):
    existing = _direct_room(user.id, other_user.id)

    resp = Client().post(
        f"{BASE}/", data={"room_type": "direct", "participant_ids": [other_user.id]},
        content_type="application/json", **auth,
    )
    assert resp.status_code == 201  # ВСЕГДА 201, даже на найденную комнату
    assert resp.json()["id"] == existing.id
    assert Room.objects.count() == 1


@pytest.mark.django_db
def test_create_direct_room_rejects_more_than_two_participants(user, other_user, third_user, auth):
    resp = Client().post(
        f"{BASE}/", data={"room_type": "direct", "participant_ids": [other_user.id, third_user.id]},
        content_type="application/json", **auth,
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Direct chats must have exactly two participants"


@pytest.mark.django_db
def test_create_group_room_any_size(user, other_user, third_user, auth):
    resp = Client().post(
        f"{BASE}/",
        data={"room_type": "group", "name": "Team", "participant_ids": [other_user.id, third_user.id]},
        content_type="application/json", **auth,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert {p["user_id"] for p in body["participants"]} == {user.id, other_user.id, third_user.id}
    admins = [p for p in body["participants"] if p["role"] == "admin"]
    assert [a["user_id"] for a in admins] == [user.id]  # только создатель — admin


# ── GET /rooms/ ──────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_list_rooms_returns_only_own_rooms(user, other_user, auth):
    mine = _direct_room(user.id, other_user.id)
    not_mine = Room.objects.create(room_type="direct")
    RoomParticipant.objects.create(room=not_mine, user_id=other_user.id, role="admin")

    resp = Client().get(f"{BASE}/", **auth)
    assert resp.status_code == 200
    ids = {r["id"] for r in resp.json()}
    assert ids == {mine.id}


@pytest.mark.django_db
def test_list_rooms_empty_when_no_rooms(auth):
    resp = Client().get(f"{BASE}/", **auth)
    assert resp.status_code == 200
    assert resp.json() == []


# ── GET /rooms/{id} ──────────────────────────────────────────────────────

@pytest.mark.django_db
def test_get_room_403_when_not_participant(user, other_user, auth):
    room = Room.objects.create(room_type="direct")
    RoomParticipant.objects.create(room=room, user_id=other_user.id, role="admin")

    resp = Client().get(f"{BASE}/{room.id}", **auth)
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Not a participant"


@pytest.mark.django_db
def test_get_room_403_when_room_does_not_exist_and_not_participant(auth):
    """Порядок проверок исходника: участие проверяется РАНЬШЕ существования
    комнаты -> несуществующий id тоже даёт 403, не 404."""
    resp = Client().get(f"{BASE}/999999", **auth)
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Not a participant"


@pytest.mark.django_db
def test_get_room_returns_room_with_participants(user, other_user, auth):
    room = _direct_room(user.id, other_user.id)
    resp = Client().get(f"{BASE}/{room.id}", **auth)
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == room.id
    assert {p["user_id"] for p in body["participants"]} == {user.id, other_user.id}
    # get_room не считает unread/last_message (исходник: RoomRead из «сырого»
    # room без _serialize_room-аннотаций) — дефолты нулевые/None.
    assert body["last_message"] is None
    assert all(p["unread_count"] == 0 for p in body["participants"])


# ── PATCH /rooms/{id} ────────────────────────────────────────────────────

@pytest.mark.django_db
def test_update_room_403_when_not_participant(other_user, auth):
    room = _group_room(other_user.id, name="Others")
    resp = Client().patch(
        f"{BASE}/{room.id}", data={"name": "Hacked"}, content_type="application/json", **auth,
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Not a participant"


@pytest.mark.django_db
def test_update_room_403_when_not_admin(user, other_user, auth):
    room = _group_room(other_user.id, user.id, name="Team")
    resp = Client().patch(
        f"{BASE}/{room.id}", data={"name": "Renamed"}, content_type="application/json", **auth,
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Only room admins can edit"


@pytest.mark.django_db
def test_update_room_400_when_direct(user, other_user, auth):
    room = _direct_room(user.id, other_user.id)
    resp = Client().patch(
        f"{BASE}/{room.id}", data={"name": "Nope"}, content_type="application/json", **auth,
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Only group rooms support name/avatar editing"


@pytest.mark.django_db
def test_update_room_sets_name_and_avatar(user, other_user, auth):
    room = _group_room(user.id, other_user.id, name="Old")
    resp = Client().patch(
        f"{BASE}/{room.id}",
        data={"name": "New name", "avatar_url": "https://example.com/a.png"},
        content_type="application/json", **auth,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "New name"
    assert body["avatar_url"] == "https://example.com/a.png"


@pytest.mark.django_db
def test_update_room_empty_string_clears_fields(user, other_user, auth):
    room = _group_room(user.id, other_user.id, name="Old")
    room.avatar_url = "https://example.com/a.png"
    room.save(update_fields=["avatar_url"])

    resp = Client().patch(
        f"{BASE}/{room.id}", data={"name": "  ", "avatar_url": ""}, content_type="application/json", **auth,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] is None
    assert body["avatar_url"] is None
