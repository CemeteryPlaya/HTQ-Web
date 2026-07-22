"""Контракт /api/messenger/v1/messages/* — паритет с
``services/messenger/app/api/v1/messages.py`` (4 эндпойнта) +
``services/messenger/app/api/v1/read.py`` (поглощён, см. ниже):

  POST /messages/                                  — send_message (201)
  GET  /messages/room/{room_id}                    — list_messages
  POST /messages/room/{room_id}/read/{message_id}   — mark_message_read (204)
  POST /messages/room/{room_id}/typing              — publish_typing (204, no-op)

``read.py::mark_read`` НЕ отдельный эндпойнт — идентичный итоговый
путь/метод, что и ``messages.py::mark_message_read``, зарегистрирован в
исходнике ПОСЛЕ него -> недостижим (см. apps/messenger/models.py::AuditLog
докстринг, apps/messenger/views.py докстринг модуля). Тесты ниже бьют в
``mark_message_read`` — единственную реально достижимую ветку.

СТРОГИЙ participant-scoping: send_message/list_messages/mark_message_read
проверяют членство вызывающего в комнате (``RoomParticipant``), буквальные
тексты/коды ошибок исходника воспроизведены как есть (см.
apps/messenger/services/messenger_service.py).
"""
from __future__ import annotations

import json
import uuid

import pytest
from django.test import Client

from apps.messenger.models import Message, Room, RoomParticipant
from apps.users.models import User, UserStatus
from htqweb.authn.jwt import issue_token_pair

BASE = "/api/messenger/v1/messages"


@pytest.fixture
def user(db):
    u = User.objects.create(username="msg2-user", email="msg2-user@htq.test", password="x", status=UserStatus.ACTIVE)
    u.set_password("S3cret!Pass1")
    u.save()
    return u


@pytest.fixture
def other_user(db):
    u = User.objects.create(username="msg2-other", email="msg2-other@htq.test", password="x", status=UserStatus.ACTIVE)
    u.set_password("S3cret!Pass1")
    u.save()
    return u


@pytest.fixture
def auth(user):
    return {"HTTP_AUTHORIZATION": f"Bearer {issue_token_pair(user)['access']}"}


@pytest.fixture
def other_auth(other_user):
    return {"HTTP_AUTHORIZATION": f"Bearer {issue_token_pair(other_user)['access']}"}


@pytest.fixture
def room(user, other_user):
    r = Room.objects.create(room_type="direct")
    RoomParticipant.objects.create(room=r, user_id=user.id, role="admin")
    RoomParticipant.objects.create(room=r, user_id=other_user.id, role="member")
    return r


def _msg(room, sender_id, content="hi", **kw):
    return Message.objects.create(room=room, sender_id=sender_id, content=content, **kw)


# ── auth ─────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_requires_jwt(room):
    assert Client().get(f"{BASE}/room/{room.id}").status_code == 401


# ── POST /messages/ ──────────────────────────────────────────────────────

@pytest.mark.django_db
def test_send_message(user, room, auth):
    resp = Client().post(
        f"{BASE}/", data=json.dumps({"room_id": room.id, "content": "hello"}),
        content_type="application/json", **auth,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["room_id"] == room.id
    assert body["sender_id"] == user.id
    assert body["content"] == "hello"
    assert body["is_encrypted"] is False
    assert body["is_edited"] is False
    assert body["attachments"] == []
    assert body["sender"]["id"] == user.id
    assert Message.objects.filter(room=room, sender_id=user.id, content="hello").exists()


@pytest.mark.django_db
def test_send_message_403_when_sender_not_participant(db):
    stranger = User.objects.create(
        username="msg2-stranger", email="msg2-stranger@htq.test", password="x", status=UserStatus.ACTIVE,
    )
    stranger.set_password("S3cret!Pass1")
    stranger.save()
    stranger_auth = {"HTTP_AUTHORIZATION": f"Bearer {issue_token_pair(stranger)['access']}"}

    other = User.objects.create(
        username="msg2-owner", email="msg2-owner@htq.test", password="x", status=UserStatus.ACTIVE,
    )
    r = Room.objects.create(room_type="group")
    RoomParticipant.objects.create(room=r, user_id=other.id, role="admin")

    resp = Client().post(
        f"{BASE}/", data=json.dumps({"room_id": r.id, "content": "hi"}),
        content_type="application/json", **stranger_auth,
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Sender is not a participant in this room"


@pytest.mark.django_db
def test_send_message_403_when_room_id_does_not_exist(auth):
    """Порядок проверок исходника (``send_message``): участие проверяется
    РАНЬШЕ существования комнаты (тот же порядок, что ``get_room`` — см.
    apps/messenger/tests/test_rooms_api.py::
    test_get_room_403_when_room_does_not_exist_and_not_participant). Ветка
    "Room not found" (rp существует, но ``Room.objects.get`` возвращает None)
    в реальности недостижима: ``RoomParticipant.room`` — CASCADE FK, комната
    не может исчезнуть, пока жив ссылающийся на неё participant."""
    resp = Client().post(
        f"{BASE}/", data=json.dumps({"room_id": 999999, "content": "hi"}),
        content_type="application/json", **auth,
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Sender is not a participant in this room"


# ── GET /messages/room/{room_id} ─────────────────────────────────────────

@pytest.mark.django_db
def test_list_messages_403_when_not_participant(auth):
    other_room = Room.objects.create(room_type="group")
    resp = Client().get(f"{BASE}/room/{other_room.id}", **auth)
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Not a participant"


@pytest.mark.django_db
def test_list_messages_returns_newest_first(user, other_user, room, auth):
    m1 = _msg(room, user.id, content="first")
    m2 = _msg(room, other_user.id, content="second")

    resp = Client().get(f"{BASE}/room/{room.id}", **auth)
    assert resp.status_code == 200
    body = resp.json()
    assert [m["id"] for m in body] == [str(m2.id), str(m1.id)]


@pytest.mark.django_db
def test_list_messages_q_filters_content(user, room, auth):
    _msg(room, user.id, content="hello world")
    _msg(room, user.id, content="goodbye")

    resp = Client().get(f"{BASE}/room/{room.id}", {"q": "hello"}, **auth)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["content"] == "hello world"


@pytest.mark.django_db
def test_list_messages_limit_offset(user, room, auth):
    for i in range(5):
        _msg(room, user.id, content=f"m{i}")

    resp = Client().get(f"{BASE}/room/{room.id}", {"limit": 2, "offset": 1}, **auth)
    assert resp.status_code == 200
    assert len(resp.json()) == 2


@pytest.mark.django_db
def test_list_messages_invalid_limit_422(room, auth):
    resp = Client().get(f"{BASE}/room/{room.id}", {"limit": 0}, **auth)
    assert resp.status_code == 422


@pytest.mark.django_db
def test_list_messages_invalid_data_type_422(room, auth):
    resp = Client().get(f"{BASE}/room/{room.id}", {"data_type": "bogus"}, **auth)
    assert resp.status_code == 422


@pytest.mark.django_db
def test_list_messages_data_type_filter_returns_empty_without_matching_attachment(user, room, auth):
    """Валидный data_type проходит валидацию, но не находит сообщение без
    вложений подходящего вида (attachments-под-задача — реальная фильтрация,
    см. test_attachments_and_data_type_filter_wired ниже для позитивного
    случая)."""
    _msg(room, user.id, content="hi")
    resp = Client().get(f"{BASE}/room/{room.id}", {"data_type": "images"}, **auth)
    assert resp.status_code == 200
    assert resp.json() == []


# ── attachment_ids (attachments-под-задача, PLAN.md §6.5) ────────────────

def _upload(room, auth, *, filename="report.txt", content=b"hello", content_type="text/plain"):
    from django.core.files.uploadedfile import SimpleUploadedFile

    upload = SimpleUploadedFile(filename, content, content_type=content_type)
    resp = Client().post(
        "/api/messenger/v1/attachments/upload/",
        data={"room_id": str(room.id), "file": upload}, **auth,
    )
    assert resp.status_code == 201, resp.content
    return resp.json()


@pytest.fixture(autouse=False)
def fake_media_storage_for_attachments(monkeypatch):
    """Attachments в этом файле нужны только для attachment_ids/data_type
    интеграции — переиспользуем тот же storage-double, что
    ``test_attachments_api.py`` (без него upload бы ушёл в реальную сеть)."""
    from apps.media_files import tasks as media_tasks
    from apps.media_files.services import upload_service as media_upload_service

    class _FakeStorage:
        def __init__(self):
            self.objects: dict[str, bytes] = {}

        def save(self, path, data, content_type=None):
            self.objects[path] = data

        def open(self, path, byte_range=None):
            data = self.objects[path]
            if byte_range is not None:
                start, end = byte_range
                return data[start: end + 1]
            return data

        def delete(self, path):
            self.objects.pop(path, None)

        def exists(self, path):
            return path in self.objects

        def size(self, path):
            return len(self.objects[path])

    storage = _FakeStorage()
    monkeypatch.setattr(media_upload_service, "get_storage", lambda bucket=None: storage)
    monkeypatch.setattr(media_tasks, "get_storage", lambda bucket=None: storage)
    return storage


@pytest.mark.usefixtures("fake_media_storage_for_attachments")
@pytest.mark.django_db
def test_send_message_attaches_uploaded_attachment(user, room, auth):
    att = _upload(room, auth, filename="pic.txt", content=b"data")
    resp = Client().post(
        f"{BASE}/", data=json.dumps({"room_id": room.id, "content": "look", "attachment_ids": [att["id"]]}),
        content_type="application/json", **auth,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert len(body["attachments"]) == 1
    assert body["attachments"][0]["id"] == att["id"]

    from apps.messenger.models import ChatAttachment

    row = ChatAttachment.objects.get(id=att["id"])
    assert str(row.message_id) == body["id"]


@pytest.mark.usefixtures("fake_media_storage_for_attachments")
@pytest.mark.django_db
def test_send_message_403_attachment_not_available_for_room(user, other_user, room, auth, other_auth):
    other_room = Room.objects.create(room_type="direct")
    RoomParticipant.objects.create(room=other_room, user_id=other_user.id, role="admin")
    att = _upload(other_room, other_auth, filename="pic.txt", content=b"data")

    resp = Client().post(
        f"{BASE}/", data=json.dumps({"room_id": room.id, "content": "hi", "attachment_ids": [att["id"]]}),
        content_type="application/json", **auth,
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "One or more attachments are not available for this room"


@pytest.mark.usefixtures("fake_media_storage_for_attachments")
@pytest.mark.django_db
def test_send_message_403_attachment_already_attached(user, room, auth):
    att = _upload(room, auth, filename="pic.txt", content=b"data")
    Client().post(
        f"{BASE}/", data=json.dumps({"room_id": room.id, "content": "first", "attachment_ids": [att["id"]]}),
        content_type="application/json", **auth,
    )
    resp = Client().post(
        f"{BASE}/", data=json.dumps({"room_id": room.id, "content": "second", "attachment_ids": [att["id"]]}),
        content_type="application/json", **auth,
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "One or more attachments are already attached to a message"


def _png_bytes() -> bytes:
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (0, 0, 255)).save(buf, format="PNG")
    return buf.getvalue()


@pytest.mark.usefixtures("fake_media_storage_for_attachments")
@pytest.mark.django_db
def test_list_messages_data_type_filter_matches_real_attachment(user, room, auth):
    att = _upload(room, auth, filename="pic.png", content=_png_bytes(), content_type="image/png")
    Client().post(
        f"{BASE}/", data=json.dumps({"room_id": room.id, "content": "photo", "attachment_ids": [att["id"]]}),
        content_type="application/json", **auth,
    )
    _msg(room, user.id, content="plain text, no attachment")

    resp = Client().get(f"{BASE}/room/{room.id}", {"data_type": "images"}, **auth)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["content"] == "photo"
    assert len(body[0]["attachments"]) == 1


@pytest.mark.usefixtures("fake_media_storage_for_attachments")
@pytest.mark.django_db
def test_list_messages_q_matches_attachment_filename(user, room, auth):
    att = _upload(room, auth, filename="invoice-2026.txt", content=b"data")
    Client().post(
        f"{BASE}/", data=json.dumps({"room_id": room.id, "content": "", "attachment_ids": [att["id"]]}),
        content_type="application/json", **auth,
    )
    _msg(room, user.id, content="unrelated")

    resp = Client().get(f"{BASE}/room/{room.id}", {"q": "invoice"}, **auth)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["attachments"][0]["filename"] == "invoice-2026.txt"


@pytest.mark.django_db
def test_list_messages_since_until(user, room, auth):
    import datetime

    from django.utils import timezone

    old = _msg(room, user.id, content="old")
    Message.objects.filter(id=old.id).update(created_at=timezone.now() - datetime.timedelta(days=2))
    recent = _msg(room, user.id, content="recent")

    since = (timezone.now() - datetime.timedelta(days=1)).isoformat()
    resp = Client().get(f"{BASE}/room/{room.id}", {"since": since}, **auth)
    assert resp.status_code == 200
    ids = {m["id"] for m in resp.json()}
    assert ids == {str(recent.id)}


# ── POST /messages/room/{room_id}/read/{message_id} ─────────────────────

@pytest.mark.django_db
def test_mark_message_read(user, other_user, room, auth):
    msg = _msg(room, other_user.id, content="unread")
    resp = Client().post(f"{BASE}/room/{room.id}/read/{msg.id}", **auth)
    assert resp.status_code == 204
    rp = RoomParticipant.objects.get(room=room, user_id=user.id)
    assert rp.last_read_message_id == msg.id


@pytest.mark.django_db
def test_mark_message_read_403_when_not_participant(auth):
    other_room = Room.objects.create(room_type="group")
    msg_id = uuid.uuid4()
    resp = Client().post(f"{BASE}/room/{other_room.id}/read/{msg_id}", **auth)
    assert resp.status_code == 403
    assert resp.json()["detail"] == "User not in room"


# ── unread_count / last_message on GET /rooms/ (list_user_rooms) ─────────

@pytest.mark.django_db
def test_room_list_unread_count_and_last_message(user, other_user, room, auth):
    from django.test import Client as C

    m1 = _msg(room, other_user.id, content="one")
    m2 = _msg(room, other_user.id, content="two")

    resp = C().get("/api/messenger/v1/rooms/", **auth)
    assert resp.status_code == 200
    body = resp.json()[0]
    assert body["last_message"]["id"] == str(m2.id)
    mine = next(p for p in body["participants"] if p["user_id"] == user.id)
    assert mine["unread_count"] == 2

    # Mark m1 as read -> only m2 remains unread.
    Client().post(f"{BASE}/room/{room.id}/read/{m1.id}", **auth)
    resp = C().get("/api/messenger/v1/rooms/", **auth)
    mine = next(p for p in resp.json()[0]["participants"] if p["user_id"] == user.id)
    assert mine["unread_count"] == 1


# ── POST /messages/room/{room_id}/typing ─────────────────────────────────

@pytest.mark.django_db
def test_publish_typing_no_op_204(room, auth):
    resp = Client().post(f"{BASE}/room/{room.id}/typing", **auth)
    assert resp.status_code == 204


@pytest.mark.django_db
def test_publish_typing_no_participant_check(auth):
    """Странность исходника: publish_typing НЕ проверяет членство вызывающего
    в комнате — воспроизведено буквально, не усилено."""
    other_room = Room.objects.create(room_type="group")
    resp = Client().post(f"{BASE}/room/{other_room.id}/typing", **auth)
    assert resp.status_code == 204
