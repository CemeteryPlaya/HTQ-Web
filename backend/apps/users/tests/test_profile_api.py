"""Contract tests for ``/api/users/v1/profile/*`` (Task 2.3).

Mirrors ``services/user/app/api/v1/profile.py`` (the FastAPI original) field
for field, precedence rule for precedence rule, status for status — EXCEPT
the avatar storage path: this port routes avatar uploads through the real
media pipeline (``apps.media_files.interface.store_file(scope="avatar",
...)``, final review of phases 2-3, Finding 2 — see ``apps.users.services.
profile_service``'s module docstring) instead of the FastAPI source's S2S
forward to media-service. ``profile_service`` does not touch storage
directly at all any more, so the avatar tests here mock the pipeline's
actual storage boundary — ``apps.media_files.services.upload_service.
get_storage`` / ``apps.media_files.tasks.get_storage`` — not
``profile_service.get_storage`` (no longer exists).
"""

import io
import json
from datetime import timedelta

import pytest
from django.test import Client
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test.client import BOUNDARY, MULTIPART_CONTENT, encode_multipart
from django.utils import timezone
from PIL import Image

from apps.core.models import ServiceStatus
from apps.media_files import tasks as media_tasks
from apps.media_files.models import FileMetadata
from apps.media_files.services import upload_service as media_upload_service
from apps.users.models import User, UserStatus
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
    """Patched into the media upload pipeline's actual storage boundary —
    ``upload_service`` writes the original, ``tasks.make_variants`` (run
    eagerly, see ``CELERY_TASK_ALWAYS_EAGER`` in test settings) reads it
    back to produce thumbnails. Same instance for both, mirroring the
    shared-bucket contract the real S3 setup gives both in production."""

    def __init__(self):
        self.objects: dict[str, tuple[bytes, str | None]] = {}

    def save(self, path, data, content_type=None):
        self.objects[path] = (data, content_type)

    def open(self, path, byte_range=None):
        data = self.objects[path][0]
        if byte_range is not None:
            start, end = byte_range
            return data[start : end + 1]
        return data

    def delete(self, path):
        self.objects.pop(path, None)

    def exists(self, path):
        return path in self.objects

    def size(self, path):
        return len(self.objects[path][0])


class _FailingStorage:
    def save(self, path, data, content_type=None):
        raise RuntimeError("storage unavailable")

    def open(self, path, byte_range=None):
        raise RuntimeError("storage unavailable")

    def delete(self, path):
        raise RuntimeError("storage unavailable")

    def exists(self, path):
        return False


@pytest.fixture
def fake_storage(monkeypatch):
    storage = _RecordingStorage()
    monkeypatch.setattr(media_upload_service, "get_storage", lambda bucket=None: storage)
    monkeypatch.setattr(media_tasks, "get_storage", lambda bucket=None: storage)
    return storage


def _disable_media():
    ServiceStatus.objects.update_or_create(app_label="media", defaults={"enabled": False})


def _png_bytes(color=(255, 0, 0), size=(8, 8)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


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


# ── PATCH profile/me — avatar (final review of phases 2-3, Finding 2:
#    routed through apps.media_files.interface.store_file(scope="avatar")) ──


@pytest.mark.django_db
def test_patch_avatar_stored_via_media_pipeline_as_public_file(active_user, fake_storage):
    token = _access_token(active_user)
    avatar = SimpleUploadedFile("me.png", _png_bytes(), content_type="image/png")
    resp = _patch_multipart(Client(), f"{BASE}/profile/me", {"avatar": avatar}, token)
    assert resp.status_code == 200
    body = resp.json()

    assert body["avatar_url"] == body["avatarUrl"]
    url = body["avatarUrl"]
    # avatar scope is public (ScopePolicy) -> canonical FileMetadata path,
    # never a signature baked in (final review Finding 1).
    assert url.startswith("/api/media/v1/files/")
    assert "?" not in url

    file_id = url.removeprefix("/api/media/v1/files/")
    meta = FileMetadata.objects.get(id=file_id)
    assert meta.owner_id == active_user.id
    assert meta.scope == "avatar"
    assert meta.is_public is True
    assert fake_storage.exists(meta.path)

    # The real pipeline now runs -> variants actually get produced
    # (ScopePolicy's avatar.variants), unlike the old direct-write path
    # where the structured `avatar` block always degraded to {}.
    assert body["avatar"]["id"] == str(meta.id)
    assert set(body["avatar"]["variants"]) == {"thumb_32", "thumb_96", "thumb_256"}
    for variant_url in body["avatar"]["variants"].values():
        assert variant_url.startswith(f"/api/media/v1/files/{meta.id}/")

    active_user.refresh_from_db()
    assert active_user.avatar_url == url


@pytest.mark.django_db
def test_patch_avatar_storage_failure_degrades_rest_of_patch_still_succeeds(
    active_user, monkeypatch,
):
    """Storage save raising inside the pipeline must NOT 500 the whole
    PATCH (degradation requirement, unchanged since task 2.3) — other
    fields still save, avatar_url is left exactly as it was before."""
    monkeypatch.setattr(media_upload_service, "get_storage", lambda bucket=None: _FailingStorage())
    token = _access_token(active_user)
    avatar = SimpleUploadedFile("me.png", _png_bytes(), content_type="image/png")
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
def test_patch_avatar_degrades_when_media_disabled(active_user, fake_storage):
    """Final review of phases 2-3, Finding 2's other half — the kill-switch
    hole: ``apps.media_files.interface.store_file``'s first statement is
    ``require_service("media")``, so a disabled ``media`` now correctly
    refuses the avatar write (``ServiceDisabled``) BEFORE anything is
    written, instead of silently bypassing the switch as the old
    direct-storage-write code did. The profile PATCH must still succeed
    (task 2.3's original degradation contract, unchanged): other fields
    save, avatar_url is left exactly as it was before."""
    _disable_media()
    token = _access_token(active_user)
    avatar = SimpleUploadedFile("me.png", _png_bytes(), content_type="image/png")
    resp = _patch_multipart(Client(), f"{BASE}/profile/me", {
        "avatar": avatar, "bio": "media is down",
    }, token)
    assert resp.status_code == 200
    body = resp.json()
    assert body["bio"] == "media is down"
    assert body["avatar_url"] is None
    active_user.refresh_from_db()
    assert active_user.bio == "media is down"
    assert active_user.avatar_url is None
    assert not fake_storage.objects  # nothing was ever written -- the switch actually held


@pytest.mark.django_db
def test_patch_profile_lost_update_race_avatar_io_window(active_user, monkeypatch):
    """Regression for review Finding 1 (lost-update race, task 2.3): the
    PATCH handler used to call ``user.save()`` with no ``update_fields``,
    so Django rewrote EVERY column from the in-memory snapshot taken at
    request start. Avatar storage I/O is a real S3/network call — anything
    that concurrently modifies this row while that call is in flight (e.g.
    an admin toggling ``is_superuser``) would get silently reverted once
    the stale in-memory ``user`` object was saved back.

    Simulated here by mutating the row, via a direct queryset ``.update()``
    (bypassing this ``user`` instance entirely), from inside the mocked
    storage's ``save()`` — which runs strictly between the profile-fields
    snapshot and the view's final ``user.save()``, i.e. exactly the race
    window (now inside the media pipeline's ``upload_service.get_storage``,
    not ``profile_service``'s own, but the same window). Fails against the
    old unconditional ``user.save()`` (reverts ``is_superuser`` to the
    stale ``False`` it had at fetch time) and passes with ``update_fields``
    restricted to the columns this request actually changed.
    """
    assert active_user.is_superuser is False

    class _RaceStorage:
        def __init__(self):
            self._data: dict[str, bytes] = {}

        def save(self, path, data, content_type=None):
            # Represents a concurrent admin write landing mid-request,
            # while this request is blocked on avatar storage I/O.
            User.objects.filter(pk=active_user.pk).update(is_superuser=True)
            self._data[path] = data

        def open(self, path, byte_range=None):
            return self._data[path]

        def delete(self, path):
            self._data.pop(path, None)

        def exists(self, path):
            return path in self._data

    monkeypatch.setattr(media_upload_service, "get_storage", lambda bucket=None: _RaceStorage())
    monkeypatch.setattr(media_tasks, "get_storage", lambda bucket=None: _RaceStorage())

    token = _access_token(active_user)
    avatar = SimpleUploadedFile("me.png", _png_bytes(), content_type="image/png")
    resp = _patch_multipart(Client(), f"{BASE}/profile/me", {
        "avatar": avatar, "bio": "concurrent-safe",
    }, token)
    assert resp.status_code == 200

    active_user.refresh_from_db()
    assert active_user.bio == "concurrent-safe"
    assert active_user.is_superuser is True  # NOT reverted by the profile save


@pytest.mark.django_db
@pytest.mark.parametrize("hostile_name", ["evil.png?x=1&y=2", "../../../etc/passwd"])
def test_patch_avatar_hostile_filename_does_not_leak_into_the_stored_path(
    active_user, fake_storage, hostile_name,
):
    """The old direct-write path derived part of the storage key from the
    client-supplied filename and needed its own sanitizer
    (``_safe_avatar_ext``, removed along with the direct-write path itself
    — final review of phases 2-3, Finding 2). The real pipeline's storage
    key (``<scope>/<yyyy>/<mm>/<uuid>/original<ext>``) is built entirely
    server-side from the scope and a fresh uuid, with ``ext`` derived from
    the REAL upload mime — not the filename — so a hostile filename simply
    cannot reach the key or the URL any more. This proves that, rather than
    re-testing a sanitizer that no longer exists."""
    token = _access_token(active_user)
    avatar = SimpleUploadedFile(hostile_name, _png_bytes(), content_type="image/png")
    resp = _patch_multipart(Client(), f"{BASE}/profile/me", {"avatar": avatar}, token)
    assert resp.status_code == 200
    url = resp.json()["avatarUrl"]

    for bad in ("?", "&", "..", " "):
        assert bad not in url

    file_id = url.removeprefix("/api/media/v1/files/")
    meta = FileMetadata.objects.get(id=file_id)
    for bad in ("?", "&", "..", " "):
        assert bad not in meta.path

    # NOT byte-equality with hostile_name: Django's own multipart parser
    # (django.http.multipartparser.MultiPartParser.sanitize_file_name)
    # unconditionally strips path separators and drops "."/".." components
    # from an uploaded file's name *before* our view code ever sees it —
    # so for "../../../etc/passwd" what reaches us as
    # ``request.FILES["avatar"].name`` is already just "passwd", never the
    # raw traversal string. Asserting verbatim storage was asserting
    # something Django itself already prevents. The property that actually
    # matters here — and that upload_service/_build_path never derive a
    # path or storage key from this field (only the scope + a fresh uuid
    # do, see the docstring above) — is that whatever ends up in
    # original_filename cannot itself carry a path component, so it can
    # never be used later to escape the intended storage prefix.
    assert "/" not in meta.original_filename
    assert "\\" not in meta.original_filename
    assert ".." not in meta.original_filename

    # Round-trip: a subsequent DELETE must still parse the stored URL and
    # clear it, and soft-delete the underlying row.
    resp2 = Client().delete(f"{BASE}/profile/avatar", **_auth(token))
    assert resp2.status_code == 204
    active_user.refresh_from_db()
    assert active_user.avatar_url is None
    meta.refresh_from_db()
    assert meta.deleted_at is not None


# ── DELETE profile/avatar ────────────────────────────────────────────────────


@pytest.mark.django_db
def test_delete_avatar_204_clears_avatar_url_and_soft_deletes_the_file(active_user, fake_storage):
    token = _access_token(active_user)
    avatar = SimpleUploadedFile("me.png", _png_bytes(), content_type="image/png")
    upload_resp = _patch_multipart(Client(), f"{BASE}/profile/me", {"avatar": avatar}, token)
    file_id = upload_resp.json()["avatarUrl"].removeprefix("/api/media/v1/files/")

    resp = Client().delete(f"{BASE}/profile/avatar", **_auth(token))
    assert resp.status_code == 204
    assert resp.content == b""
    active_user.refresh_from_db()
    assert active_user.avatar_url is None

    meta = FileMetadata.objects.get(id=file_id)
    assert meta.deleted_at is not None


@pytest.mark.django_db
def test_delete_avatar_with_legacy_raw_key_url_clears_field_but_skips_cleanup(active_user):
    """Pre-fix rows (old direct-write path, raw storage key baked straight
    into the URL) don't match ``_FILE_ID_RE`` any more (see
    ``profile_service``'s module docstring) — ``delete_avatar_object`` has
    no ``FileMetadata`` id to soft-delete, so cleanup is skipped. The
    user-facing DELETE must still succeed and clear ``avatar_url`` —
    documented gap, not a crash."""
    old_key = f"avatars/{active_user.id}/old.png"
    active_user.avatar_url = f"/api/media/v1/files/{old_key}?sig=abc&exp=999999999999"
    active_user.save(update_fields=["avatar_url"])
    token = _access_token(active_user)

    resp = Client().delete(f"{BASE}/profile/avatar", **_auth(token))
    assert resp.status_code == 204
    active_user.refresh_from_db()
    assert active_user.avatar_url is None


@pytest.mark.django_db
def test_delete_avatar_no_avatar_is_a_noop_204(active_user, fake_storage):
    assert active_user.avatar_url is None
    token = _access_token(active_user)
    resp = Client().delete(f"{BASE}/profile/avatar", **_auth(token))
    assert resp.status_code == 204


def test_delete_avatar_unauthenticated_401(db):
    resp = Client().delete(f"{BASE}/profile/avatar")
    assert resp.status_code == 401


@pytest.mark.django_db
def test_delete_avatar_advances_updated_at(active_user, fake_storage):
    """R6 Fix 2: ``remove_avatar``'s partial save uses
    ``update_fields=["avatar_url"]`` — Django does NOT auto-add an
    ``auto_now`` field to a partial ``update_fields`` save, so without an
    explicit ``updated_at`` in that list, the column would never advance."""
    old = timezone.now() - timedelta(days=1)
    User.objects.filter(pk=active_user.pk).update(updated_at=old)
    active_user.refresh_from_db()
    assert active_user.updated_at == old

    token = _access_token(active_user)
    resp = Client().delete(f"{BASE}/profile/avatar", **_auth(token))
    assert resp.status_code == 204

    active_user.refresh_from_db()
    assert active_user.updated_at > old


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


@pytest.mark.django_db
def test_change_password_advances_updated_at(active_user):
    """R6 Fix 2: ``change_password``'s partial save uses
    ``update_fields=["password", "must_change_password"]`` — without an
    explicit ``updated_at`` in that list, ``auto_now`` would not fire."""
    old = timezone.now() - timedelta(days=1)
    User.objects.filter(pk=active_user.pk).update(updated_at=old)
    active_user.refresh_from_db()
    assert active_user.updated_at == old

    token = _access_token(active_user)
    resp = Client().post(f"{BASE}/profile/change-password/", data=json.dumps({
        "current_password": "S3cret!", "new_password": "N3wPassw0rd!",
    }), content_type="application/json", **_auth(token))
    assert resp.status_code == 200

    active_user.refresh_from_db()
    assert active_user.updated_at > old
