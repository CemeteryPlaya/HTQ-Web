"""Contract tests for ``/api/users/v1/profile/*`` (Task 2.3).

Mirrors ``services/user/app/api/v1/profile.py`` (the FastAPI original) field
for field, precedence rule for precedence rule, status for status — EXCEPT
the avatar storage path (decision Р3, see ``apps.users.services.
profile_service``'s module docstring): we write directly to
``htqweb.storage`` instead of forwarding to media-service over S2S, so the
avatar tests here mock ``get_storage`` rather than an httpx call.
"""

import json

import pytest
from django.conf import settings
from django.test import Client
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test.client import BOUNDARY, MULTIPART_CONTENT, encode_multipart

from apps.users.models import User, UserStatus
from apps.users.services import profile_service
from htqweb.authn.jwt import issue_token_pair

BASE = "/api/users/v1"


@pytest.fixture
def active_user(db):
    u = User.objects.create(username="alice", email="alice@htq.test", password="x",
                            status=UserStatus.ACTIVE, first_name="Alice", last_name="Smith")
    u.set_password("S3cret!")
    u.save()
    return u


def _access_token(user) -> str:
    return issue_token_pair(user)["access"]


def _auth(token: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


def _patch_multipart(client: Client, path: str, data: dict, token: str):
    body = encode_multipart(BOUNDARY, data)
    return client.patch(path, data=body, content_type=MULTIPART_CONTENT, **_auth(token))


class _RecordingStorage:
    def __init__(self):
        self.saved = []
        self.deleted = []

    def save(self, path, data, content_type=None):
        self.saved.append((path, data, content_type))

    def delete(self, path):
        self.deleted.append(path)


class _FailingStorage:
    def save(self, path, data, content_type=None):
        raise RuntimeError("storage unavailable")

    def delete(self, path):
        raise RuntimeError("storage unavailable")


@pytest.fixture
def fake_storage(monkeypatch):
    storage = _RecordingStorage()
    buckets_requested = []

    def fake_get_storage(bucket=None):
        buckets_requested.append(bucket)
        return storage

    monkeypatch.setattr(profile_service, "get_storage", fake_get_storage)
    storage.buckets_requested = buckets_requested
    return storage


# ── GET profile/me (+ alias) ─────────────────────────────────────────────────


@pytest.mark.django_db
def test_get_profile_me_200_full_dual_case_field_set(active_user):
    resp = Client().get(f"{BASE}/profile/me", **_auth(_access_token(active_user)))
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {
        "id", "username", "email",
        "first_name", "last_name", "firstName", "lastName", "patronymic",
        "display_name", "fio", "bio", "phone",
        "avatar_url", "avatarUrl", "avatar", "settings",
        "roles", "department", "department_id", "position",
        "must_change_password", "date_joined", "last_login",
        "created_at", "updated_at",
    }
    assert body["id"] == str(active_user.id)
    assert body["username"] == "alice"
    assert body["first_name"] == body["firstName"] == "Alice"
    assert body["last_name"] == body["lastName"] == "Smith"
    assert body["fio"] == "Smith Alice"
    assert body["avatar_url"] is None
    assert body["avatarUrl"] is None
    assert body["avatar"] is None
    assert body["settings"] == {}
    assert body["roles"] == ["user"]
    assert body["department"] is None
    assert body["department_id"] is None
    assert body["position"] is None
    assert body["must_change_password"] is False


@pytest.mark.django_db
def test_get_profile_slash_alias_200(active_user):
    resp = Client().get(f"{BASE}/profile/", **_auth(_access_token(active_user)))
    assert resp.status_code == 200
    assert resp.json()["username"] == "alice"


def test_get_profile_unauthenticated_401(db):
    resp = Client().get(f"{BASE}/profile/me")
    assert resp.status_code == 401
    assert "detail" in resp.json()


# ── PATCH profile/me — field precedence ─────────────────────────────────────


@pytest.mark.django_db
def test_patch_snake_case_fields_updates(active_user):
    token = _access_token(active_user)
    resp = _patch_multipart(Client(), f"{BASE}/profile/me", {
        "first_name": "Alicia", "last_name": "Jones", "bio": "hello",
    }, token)
    assert resp.status_code == 200
    body = resp.json()
    assert body["first_name"] == body["firstName"] == "Alicia"
    assert body["last_name"] == body["lastName"] == "Jones"
    assert body["bio"] == "hello"
    active_user.refresh_from_db()
    assert active_user.first_name == "Alicia"
    assert active_user.bio == "hello"


@pytest.mark.django_db
def test_patch_camel_case_fields_updates(active_user):
    token = _access_token(active_user)
    resp = _patch_multipart(Client(), f"{BASE}/profile/me", {
        "firstName": "Ali", "lastName": "Jonesy",
    }, token)
    assert resp.status_code == 200
    body = resp.json()
    assert body["first_name"] == body["firstName"] == "Ali"
    assert body["last_name"] == body["lastName"] == "Jonesy"


@pytest.mark.django_db
def test_patch_both_cases_present_prefers_camel_case(active_user):
    token = _access_token(active_user)
    resp = _patch_multipart(Client(), f"{BASE}/profile/me", {
        "firstName": "CamelWins", "first_name": "SnakeLoses",
        "lastName": "CamelLastWins", "last_name": "SnakeLastLoses",
    }, token)
    assert resp.status_code == 200
    body = resp.json()
    assert body["first_name"] == body["firstName"] == "CamelWins"
    assert body["last_name"] == body["lastName"] == "CamelLastWins"
    active_user.refresh_from_db()
    assert active_user.first_name == "CamelWins"
    assert active_user.last_name == "CamelLastWins"


@pytest.mark.django_db
def test_patch_settings_json_string_parsed_into_user_settings(active_user):
    token = _access_token(active_user)
    resp = _patch_multipart(Client(), f"{BASE}/profile/me", {
        "settings": json.dumps({"theme": "dark", "locale": "ru"}),
    }, token)
    assert resp.status_code == 200
    body = resp.json()
    assert body["settings"] == {"theme": "dark", "locale": "ru"}
    active_user.refresh_from_db()
    assert active_user.settings == {"theme": "dark", "locale": "ru"}


@pytest.mark.django_db
def test_patch_settings_invalid_json_400(active_user):
    token = _access_token(active_user)
    resp = _patch_multipart(Client(), f"{BASE}/profile/me", {
        "settings": "{not valid json",
    }, token)
    assert resp.status_code == 400
    assert "detail" in resp.json()
    active_user.refresh_from_db()
    assert active_user.settings == {}


@pytest.mark.django_db
def test_patch_settings_valid_json_but_not_object_400(active_user):
    token = _access_token(active_user)
    resp = _patch_multipart(Client(), f"{BASE}/profile/me", {
        "settings": json.dumps([1, 2, 3]),
    }, token)
    assert resp.status_code == 400
    assert resp.json()["detail"] == "settings must be a JSON object"
    active_user.refresh_from_db()
    assert active_user.settings == {}


@pytest.mark.django_db
def test_patch_unauthenticated_401(db):
    resp = _patch_multipart(Client(), f"{BASE}/profile/me", {"bio": "x"}, token="garbage")
    assert resp.status_code == 401


# ── PATCH profile/me — avatar (decision Р3: direct htqweb.storage write) ────


@pytest.mark.django_db
def test_patch_avatar_file_stored_and_signed_url_returned(active_user, fake_storage):
    token = _access_token(active_user)
    avatar = SimpleUploadedFile("me.png", b"png-bytes", content_type="image/png")
    resp = _patch_multipart(Client(), f"{BASE}/profile/me", {"avatar": avatar}, token)
    assert resp.status_code == 200
    body = resp.json()

    assert body["avatar_url"] == body["avatarUrl"]
    url = body["avatarUrl"]
    assert url.startswith(f"/api/media/v1/files/avatars/{active_user.id}/")
    assert "?sig=" in url
    assert "&exp=" in url
    # The image-variant worker isn't reproduced in this port (task brief) —
    # our own key shape never matches the FastAPI source's UUID-file-id
    # regex, so the structured `avatar` block degrades to the
    # legacy/external-URL branch: id=None, variants={}.
    assert body["avatar"] == {"id": None, "url": url, "variants": {}}

    assert fake_storage.buckets_requested == [settings.MEDIA_S3_BUCKET]
    assert len(fake_storage.saved) == 1
    saved_key, saved_data, saved_content_type = fake_storage.saved[0]
    assert saved_data == b"png-bytes"
    assert saved_content_type == "image/png"
    assert saved_key.startswith(f"avatars/{active_user.id}/")

    active_user.refresh_from_db()
    assert active_user.avatar_url == url


@pytest.mark.django_db
def test_patch_avatar_save_failure_degrades_rest_of_patch_still_succeeds(
    active_user, monkeypatch,
):
    """Storage save raising must NOT 500 the whole PATCH (task brief's
    degradation requirement) — other fields still save, avatar_url is left
    exactly as it was before."""
    monkeypatch.setattr(profile_service, "get_storage", lambda bucket=None: _FailingStorage())
    token = _access_token(active_user)
    avatar = SimpleUploadedFile("me.png", b"png-bytes", content_type="image/png")
    resp = _patch_multipart(Client(), f"{BASE}/profile/me", {
        "avatar": avatar, "bio": "still saved",
    }, token)
    assert resp.status_code == 200
    body = resp.json()
    assert body["bio"] == "still saved"
    assert body["avatar_url"] is None  # unchanged (was None before the PATCH)
    active_user.refresh_from_db()
    assert active_user.bio == "still saved"
    assert active_user.avatar_url is None


@pytest.mark.django_db
def test_patch_profile_lost_update_race_avatar_io_window(active_user, monkeypatch):
    """Regression for review Finding 1 (lost-update race): the PATCH handler
    used to call ``user.save()`` with no ``update_fields``, so Django
    rewrote EVERY column from the in-memory snapshot taken at request
    start. Avatar storage I/O is a real S3/network call — anything that
    concurrently modifies this row while that call is in flight (e.g. an
    admin toggling ``is_superuser``) would get silently reverted once the
    stale in-memory ``user`` object was saved back.

    Simulated here by mutating the row, via a direct queryset ``.update()``
    (bypassing this ``user`` instance entirely), from inside the mocked
    storage's ``save()`` — which runs strictly between the profile-fields
    snapshot and the view's final ``user.save()``, i.e. exactly the race
    window. Fails against the old unconditional ``user.save()`` (reverts
    ``is_superuser`` to the stale ``False`` it had at fetch time) and
    passes with ``update_fields`` restricted to the columns this request
    actually changed.
    """
    assert active_user.is_superuser is False

    class _RaceStorage:
        def save(self, path, data, content_type=None):
            # Represents a concurrent admin write landing mid-request,
            # while this request is blocked on avatar storage I/O.
            User.objects.filter(pk=active_user.pk).update(is_superuser=True)

        def delete(self, path):
            pass

    monkeypatch.setattr(profile_service, "get_storage", lambda bucket=None: _RaceStorage())

    token = _access_token(active_user)
    avatar = SimpleUploadedFile("me.png", b"png-bytes", content_type="image/png")
    resp = _patch_multipart(Client(), f"{BASE}/profile/me", {
        "avatar": avatar, "bio": "concurrent-safe",
    }, token)
    assert resp.status_code == 200

    active_user.refresh_from_db()
    assert active_user.bio == "concurrent-safe"
    assert active_user.is_superuser is True  # NOT reverted by the profile save


# ── PATCH profile/me — avatar filename/ext sanitization (review Finding 2) ──


@pytest.mark.django_db
@pytest.mark.parametrize("hostile_name", ["evil.png?x=1&y=2", "../../../etc/passwd"])
def test_patch_avatar_hostile_filename_sanitized_and_round_trips(
    active_user, fake_storage, hostile_name,
):
    token = _access_token(active_user)
    avatar = SimpleUploadedFile(hostile_name, b"png-bytes", content_type="image/png")
    resp = _patch_multipart(Client(), f"{BASE}/profile/me", {"avatar": avatar}, token)
    assert resp.status_code == 200
    body = resp.json()
    url = body["avatarUrl"]

    # Split off the legitimate ?sig=...&exp=... signed query before
    # asserting — only the key portion (path_part) must be clean.
    path_part, _, query_part = url.partition("?")
    for bad in ("?", "&", "..", " "):
        assert bad not in path_part
    assert query_part.startswith("sig=")

    assert len(fake_storage.saved) == 1
    saved_key = fake_storage.saved[0][0]
    for bad in ("?", "&", "..", " "):
        assert bad not in saved_key
    assert saved_key.startswith(f"avatars/{active_user.id}/")

    # Round-trip: a subsequent DELETE must still parse the stored URL and
    # clear it — proof _AVATAR_KEY_RE isn't mis-parsing an injected key.
    resp2 = Client().delete(f"{BASE}/profile/avatar", **_auth(token))
    assert resp2.status_code == 204
    active_user.refresh_from_db()
    assert active_user.avatar_url is None
    assert fake_storage.deleted == [saved_key]


@pytest.mark.parametrize(
    "filename,content_type,expected_ext",
    [
        ("me.png", "image/png", ".png"),
        ("me.jpg", "image/jpeg", ".jpg"),
        ("me.gif", "image/gif", ".gif"),
        ("me.webp", "image/webp", ".webp"),
        # Content-type wins even over a mismatched/hostile filename.
        ("evil.png?x=1&y=2", "image/png", ".png"),
        # No usable content-type: filename tail fallback, but only if it
        # is itself a strict lowercase alnum token.
        ("photo.PNG", None, ".png"),
        ("photo.PNG", "application/octet-stream", ".png"),
        # Hostile/unsafe tails never pass through — safe default instead.
        ("evil.png?x=1&y=2", None, ".jpg"),
        ("../../../etc/passwd", None, ".jpg"),
        ("../../../etc/passwd", "image/png", ".png"),
        ("noext", None, ".jpg"),
    ],
)
def test_safe_avatar_ext_sanitizes(filename, content_type, expected_ext):
    assert profile_service._safe_avatar_ext(filename, content_type) == expected_ext


# ── DELETE profile/avatar ────────────────────────────────────────────────────


@pytest.mark.django_db
def test_delete_avatar_204_clears_avatar_url(active_user, fake_storage):
    old_key = f"avatars/{active_user.id}/old.png"
    active_user.avatar_url = f"/api/media/v1/files/{old_key}?sig=abc&exp=999999999999"
    active_user.save(update_fields=["avatar_url"])
    token = _access_token(active_user)
    resp = Client().delete(f"{BASE}/profile/avatar", **_auth(token))
    assert resp.status_code == 204
    assert resp.content == b""
    active_user.refresh_from_db()
    assert active_user.avatar_url is None
    assert fake_storage.deleted == [old_key]


@pytest.mark.django_db
def test_delete_avatar_no_avatar_is_a_noop_204(active_user, fake_storage):
    assert active_user.avatar_url is None
    token = _access_token(active_user)
    resp = Client().delete(f"{BASE}/profile/avatar", **_auth(token))
    assert resp.status_code == 204
    assert fake_storage.deleted == []


def test_delete_avatar_unauthenticated_401(db):
    resp = Client().delete(f"{BASE}/profile/avatar")
    assert resp.status_code == 401


# ── POST profile/change-password ─────────────────────────────────────────────


@pytest.mark.django_db
def test_change_password_happy_path_200(active_user):
    token = _access_token(active_user)
    resp = Client().post(f"{BASE}/profile/change-password/", data=json.dumps({
        "current_password": "S3cret!", "new_password": "N3wPassw0rd!",
    }), content_type="application/json", **_auth(token))
    assert resp.status_code == 200
    assert resp.json() == {"detail": "Password changed successfully"}
    active_user.refresh_from_db()
    assert active_user.check_password("N3wPassw0rd!") is True
    assert active_user.check_password("S3cret!") is False


@pytest.mark.django_db
def test_change_password_no_trailing_slash_also_works(active_user):
    token = _access_token(active_user)
    resp = Client().post(f"{BASE}/profile/change-password", data=json.dumps({
        "current_password": "S3cret!", "new_password": "N3wPassw0rd!",
    }), content_type="application/json", **_auth(token))
    assert resp.status_code == 200


@pytest.mark.django_db
def test_change_password_wrong_current_password_rejected_400(active_user):
    token = _access_token(active_user)
    resp = Client().post(f"{BASE}/profile/change-password/", data=json.dumps({
        "current_password": "wrong", "new_password": "N3wPassw0rd!",
    }), content_type="application/json", **_auth(token))
    assert resp.status_code == 400
    assert resp.json() == {"detail": "Current password is incorrect"}
    active_user.refresh_from_db()
    assert active_user.check_password("S3cret!") is True


@pytest.mark.django_db
def test_change_password_missing_current_password_rejected_400(active_user):
    token = _access_token(active_user)
    resp = Client().post(f"{BASE}/profile/change-password/", data=json.dumps({
        "new_password": "N3wPassw0rd!",
    }), content_type="application/json", **_auth(token))
    assert resp.status_code == 400


@pytest.mark.django_db
def test_change_password_forced_reset_allows_missing_current_password(db):
    u = User.objects.create(username="reset1", email="reset1@htq.test", password="x",
                            status=UserStatus.ACTIVE, must_change_password=True)
    u.set_password("OldTemp1!")
    u.save()
    token = _access_token(u)
    resp = Client().post(f"{BASE}/profile/change-password/", data=json.dumps({
        "new_password": "BrandNew1!",
    }), content_type="application/json", **_auth(token))
    assert resp.status_code == 200
    u.refresh_from_db()
    assert u.check_password("BrandNew1!") is True
    assert u.must_change_password is False


def test_change_password_unauthenticated_401(db):
    resp = Client().post(f"{BASE}/profile/change-password/", data=json.dumps({
        "new_password": "N3wPassw0rd!",
    }), content_type="application/json")
    assert resp.status_code == 401
