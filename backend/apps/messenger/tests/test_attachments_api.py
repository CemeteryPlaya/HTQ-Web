"""Контракт /api/messenger/v1/attachments/* — паритет с
``services/messenger/app/api/v1/attachments.py`` (3 эндпойнта):

  POST /attachments/upload/           — upload_attachment (201, multipart)
  GET  /attachments/file/{id}         — serve_attachment (302 redirect)
  GET  /attachments/file/{id}/thumb   — serve_attachment_thumb (302 redirect)

Байты идут через ``apps.media_files.interface.store_file(scope="chat")`` —
storage мокается тем же паттерном, что ``apps/hr/tests/
test_department_files_api.py``/``apps/mail/tests/test_attachment_service.py``
(``_FakeStorage`` + monkeypatch ``upload_service.get_storage``), ПЛЮС
``apps.media_files.tasks.get_storage`` (та же фейковая storage) — "chat"
scope несёт ``variants=("thumb_256",)`` в media_files' scope_policy, значит
загрузка картинки ставит в очередь ``make_variants`` (CELERY_TASK_ALWAYS_
EAGER=True в тестах — исполняется синхронно ПРЯМО внутри store_file()); без
этого патча тест ушёл бы в реальную сеть/MinIO за несуществующим бакетом.

Signed-URL контракт (``?sig=&exp=``) переиспользует ``htqweb.storage.
signed_url`` (см. ``apps/messenger/services/attachment_service.py``
докстринг) — тесты используют ``signed_query``/``sign`` оттуда напрямую,
не полагаясь на строку из ответа upload (та же подпись, другой TTL/`exp`
на каждый вызов).
"""
from __future__ import annotations

import io
import uuid

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from PIL import Image

from apps.messenger.models import ChatAttachment, Room, RoomParticipant
from apps.users.models import User, UserStatus
from htqweb.authn.jwt import issue_token_pair
from htqweb.storage import signed_query

BASE = "/api/messenger/v1/attachments"


class _FakeStorage:
    """In-memory htqweb.storage.Storage double — see module docstring."""

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


@pytest.fixture(autouse=True)
def fake_media_storage(monkeypatch):
    from apps.media_files import tasks as media_tasks
    from apps.media_files.services import upload_service as media_upload_service

    storage = _FakeStorage()
    monkeypatch.setattr(media_upload_service, "get_storage", lambda bucket=None: storage)
    monkeypatch.setattr(media_tasks, "get_storage", lambda bucket=None: storage)
    return storage


def _user_auth(username: str):
    user = User.objects.create(
        username=username, email=f"{username}@htq.test", password="x", status=UserStatus.ACTIVE,
    )
    user.set_password("S3cret!Pass1")
    user.save()
    return user, {"HTTP_AUTHORIZATION": f"Bearer {issue_token_pair(user)['access']}"}


@pytest.fixture
def user(db):
    u, _ = _user_auth("att-user")
    return u


@pytest.fixture
def other_user(db):
    u, _ = _user_auth("att-other")
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


def _png_bytes(size=(64, 40), color=(255, 0, 0)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def _sig_exp(attachment_id) -> tuple[str, int]:
    query = signed_query(str(attachment_id))
    parts = dict(p.split("=", 1) for p in query.split("&"))
    return parts["sig"], int(parts["exp"])


# ── auth ─────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_upload_requires_jwt(room):
    upload = SimpleUploadedFile("a.txt", b"hi", content_type="text/plain")
    resp = Client().post(f"{BASE}/upload/", data={"room_id": str(room.id), "file": upload})
    assert resp.status_code == 401


# ── POST /attachments/upload/ ────────────────────────────────────────────

@pytest.mark.django_db
def test_upload_text_attachment(user, room, auth):
    upload = SimpleUploadedFile("report.txt", b"hello chat", content_type="text/plain")
    resp = Client().post(
        f"{BASE}/upload/", data={"room_id": str(room.id), "file": upload}, **auth,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["room_id"] == room.id
    assert body["message_id"] is None
    assert body["filename"] == "report.txt"
    assert body["content_type"] == "text/plain"
    assert body["data_type"] == "documents"
    assert body["size"] == len(b"hello chat")
    assert body["file_metadata_id"]
    assert body["thumbnail_path"] is None
    assert body["thumbnail_url"] is None
    assert body["url"].startswith(f"{BASE}/file/")

    row = ChatAttachment.objects.get(id=body["id"])
    assert row.uploaded_by == user.id
    assert row.room_id == room.id
    assert row.file_metadata_id is not None
    assert row.storage_path


@pytest.mark.django_db
def test_upload_image_generates_thumbnail(user, room, auth):
    upload = SimpleUploadedFile("photo.png", _png_bytes(), content_type="image/png")
    resp = Client().post(
        f"{BASE}/upload/", data={"room_id": str(room.id), "file": upload}, **auth,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["data_type"] == "images"
    assert body["width"] == 64
    assert body["height"] == 40
    assert body["thumbnail_path"]
    assert body["thumbnail_url"] is not None
    assert "/thumb" in body["thumbnail_url"]


@pytest.mark.django_db
def test_upload_403_when_not_participant(other_user, auth):
    """``auth`` belongs to ``user`` fixture (not created here, only via
    ``_user_auth`` — need a room where the caller is NOT a participant)."""
    room = Room.objects.create(room_type="direct")
    RoomParticipant.objects.create(room=room, user_id=other_user.id, role="admin")
    upload = SimpleUploadedFile("a.txt", b"x", content_type="text/plain")
    resp = Client().post(f"{BASE}/upload/", data={"room_id": str(room.id), "file": upload}, **auth)
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Not a participant"


@pytest.mark.django_db
def test_upload_room_not_found_branch_at_service_level(monkeypatch, user):
    """Порт ``attachments.py::upload_attachment``'s "Room not found" 404
    ветка проверяется НАПРЯМУЮ на сервисном слое (не через HTTP): точно как
    ``messenger_service.py::send_message``'s аналогичная ветка (см.
    ``test_messages_api.py::test_send_message_403_when_room_id_does_not_exist``
    докстринг), она недостижима через реальный HTTP-запрос —
    ``RoomParticipant.room`` CASCADE FK не даёт участнику пережить удаление
    комнаты, поэтому "участник существует, а комнаты нет" не воспроизводимо
    без прямого мока."""
    from apps.messenger.services import attachment_service

    monkeypatch.setattr(
        attachment_service.RoomParticipant.objects, "filter",
        lambda **kw: type("_Q", (), {"exists": lambda self: True})(),
    )
    upload = SimpleUploadedFile("a.txt", b"x", content_type="text/plain")
    with pytest.raises(attachment_service.RoomNotFound):
        attachment_service.upload_attachment(user.id, room_id=999999, upload=upload)


@pytest.mark.django_db
def test_upload_missing_file_422(room, auth):
    resp = Client().post(f"{BASE}/upload/", data={"room_id": str(room.id)}, **auth)
    assert resp.status_code == 422


@pytest.mark.django_db
def test_upload_missing_room_id_422(room, auth):
    upload = SimpleUploadedFile("a.txt", b"x", content_type="text/plain")
    resp = Client().post(f"{BASE}/upload/", data={"file": upload}, **auth)
    assert resp.status_code == 422


# ── GET /attachments/file/{id} ───────────────────────────────────────────

@pytest.mark.django_db
def test_serve_attachment_redirects(user, room, auth):
    upload = SimpleUploadedFile("report.txt", b"hello chat", content_type="text/plain")
    created = Client().post(
        f"{BASE}/upload/", data={"room_id": str(room.id), "file": upload}, **auth,
    ).json()

    sig, exp = _sig_exp(created["id"])
    resp = Client().get(f"{BASE}/file/{created['id']}", {"sig": sig, "exp": exp}, **auth)
    assert resp.status_code == 302
    assert resp["Location"]


@pytest.mark.django_db
def test_serve_attachment_no_jwt_still_works_via_signature(user, room, auth):
    """Порт get_optional_user: <img src> без Authorization — sig/exp
    достаточно, если запрос анонимный."""
    upload = SimpleUploadedFile("report.txt", b"hello chat", content_type="text/plain")
    created = Client().post(
        f"{BASE}/upload/", data={"room_id": str(room.id), "file": upload}, **auth,
    ).json()

    sig, exp = _sig_exp(created["id"])
    resp = Client().get(f"{BASE}/file/{created['id']}", {"sig": sig, "exp": exp})
    assert resp.status_code == 302


@pytest.mark.django_db
def test_serve_attachment_403_not_participant_with_jwt(user, room, auth, other_user):
    """Указанный JWT есть -> participant-scoping применяется (в отличие от
    анонимного случая выше)."""
    outsider_user, outsider_auth = _user_auth("att-outsider")
    upload = SimpleUploadedFile("report.txt", b"hello chat", content_type="text/plain")
    created = Client().post(
        f"{BASE}/upload/", data={"room_id": str(room.id), "file": upload}, **auth,
    ).json()

    sig, exp = _sig_exp(created["id"])
    resp = Client().get(f"{BASE}/file/{created['id']}", {"sig": sig, "exp": exp}, **outsider_auth)
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Not a participant"


@pytest.mark.django_db
def test_serve_attachment_invalid_signature_403(user, room, auth):
    upload = SimpleUploadedFile("report.txt", b"hello chat", content_type="text/plain")
    created = Client().post(
        f"{BASE}/upload/", data={"room_id": str(room.id), "file": upload}, **auth,
    ).json()

    resp = Client().get(f"{BASE}/file/{created['id']}", {"sig": "bogus", "exp": 9999999999})
    assert resp.status_code == 403


@pytest.mark.django_db
def test_serve_attachment_missing_sig_422():
    resp = Client().get(f"{BASE}/file/{uuid.uuid4()}")
    assert resp.status_code == 422


@pytest.mark.django_db
def test_serve_attachment_404_unknown_id():
    unknown_id = uuid.uuid4()
    sig, exp = _sig_exp(unknown_id)
    resp = Client().get(f"{BASE}/file/{unknown_id}", {"sig": sig, "exp": exp})
    assert resp.status_code == 404


# ── GET /attachments/file/{id}/thumb ─────────────────────────────────────

@pytest.mark.django_db
def test_serve_attachment_thumb_redirects_for_image(user, room, auth):
    upload = SimpleUploadedFile("photo.png", _png_bytes(), content_type="image/png")
    created = Client().post(
        f"{BASE}/upload/", data={"room_id": str(room.id), "file": upload}, **auth,
    ).json()

    sig, exp = _sig_exp(created["id"])
    resp = Client().get(f"{BASE}/file/{created['id']}/thumb", {"sig": sig, "exp": exp}, **auth)
    assert resp.status_code == 302


@pytest.mark.django_db
def test_serve_attachment_thumb_falls_back_to_original_for_non_image(user, room, auth):
    """``thumbnail_path`` NULL (не-картинка) — редирект на оригинал, не 404."""
    upload = SimpleUploadedFile("report.txt", b"hello chat", content_type="text/plain")
    created = Client().post(
        f"{BASE}/upload/", data={"room_id": str(room.id), "file": upload}, **auth,
    ).json()
    assert created["thumbnail_path"] is None

    sig, exp = _sig_exp(created["id"])
    resp = Client().get(f"{BASE}/file/{created['id']}/thumb", {"sig": sig, "exp": exp}, **auth)
    assert resp.status_code == 302
