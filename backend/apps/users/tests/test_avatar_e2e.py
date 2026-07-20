"""Cross-app end-to-end round-trip: users' profile-avatar upload -> media's
signed-URL serving (Task 3.5).

These tests legitimately straddle two apps and are deliberately placed here
(in ``apps.users.tests``, not ``apps.media_files.tests``) because the
user-facing flow starts in ``users`` — an authenticated ``PATCH
profile/me`` — and only crosses into ``media`` at the point where the
browser follows the ``avatar_url`` it got back. Task 2.3
(``profile_service.save_avatar``, decision Р3) wrote that URL — shaped
``/api/media/v1/files/<key>?sig=&exp=`` — before task 3.3's
``apps.media_files.views.serve_raw_key`` (the only thing that can actually
serve it) existed. Nobody had proven the two halves fit together; that is
what this module verifies.

Both ``apps.users.services.profile_service`` and ``apps.media_files.views``
call ``htqweb.storage.get_storage`` independently — in production both
resolve to the same S3 bucket (``settings.MEDIA_S3_BUCKET``), so here both
are monkeypatched to the SAME in-memory ``_RecordingStorage`` instance (same
pattern ``apps/media_files/tests/test_serving_api.py``'s
``test_avatar_save_and_serve_end_to_end`` already established) — this
reproduces the shared-bucket contract deterministically without touching a
real filesystem or S3 in the test suite. ``STORAGE_BACKEND`` is forced to
``"local"`` (via the autouse fixture below) so ``serve_raw_key`` streams
bytes directly instead of issuing a 302 to a presigned URL that only makes
sense against a real S3/MinIO endpoint — a plain ``Client().get(...)`` can't
follow a redirect to an external host anyway, and the task's core assertion
(byte-identical content) needs a body on the response it actually gets.
"""

from __future__ import annotations

import io
import time

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.test.client import BOUNDARY, MULTIPART_CONTENT, encode_multipart
from PIL import Image

from apps.core.models import ServiceStatus
from apps.media_files import views as media_views
from apps.users.models import User, UserStatus
from apps.users.services import profile_service
from htqweb.authn.jwt import issue_token_pair
from htqweb.storage.signed_url import _digest

BASE_USERS = "/api/users/v1"


@pytest.fixture(autouse=True)
def _local_storage_backend(settings):
    # serve_raw_key redirects (302) instead of streaming when
    # STORAGE_BACKEND == "s3" (STRUCTURE.md §7.1's private-file flow) — a
    # bare 302 to a fake presigned URL isn't fetchable by django.test.Client
    # and defeats the point of this module (real bytes, real comparison).
    settings.STORAGE_BACKEND = "local"


class _RecordingStorage:
    """Minimal in-memory ``htqweb.storage.Storage`` double, shared between
    the writer (profile_service) and the reader (media_files.views) so a
    write from one is visible to a read from the other — exactly what the
    real shared S3 bucket gives both sides in production."""

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

    def presigned_get_url(self, path, ttl=None):  # pragma: no cover - STORAGE_BACKEND=local
        raise NotImplementedError("not used at STORAGE_BACKEND=local")


@pytest.fixture
def shared_storage(monkeypatch):
    storage = _RecordingStorage()
    monkeypatch.setattr(profile_service, "get_storage", lambda bucket=None: storage)
    monkeypatch.setattr(media_views, "get_storage", lambda bucket=None: storage)
    return storage


def _make_user(username: str) -> User:
    u = User.objects.create(
        username=username, email=f"{username}@htq.test", password="x",
        status=UserStatus.ACTIVE, first_name="Test", last_name="User",
    )
    u.set_password("S3cret!")
    u.save()
    return u


@pytest.fixture
def user(db):
    return _make_user("avatarowner")


def _token(u: User) -> str:
    return issue_token_pair(u)["access"]


def _auth(token: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


def _png_bytes(color: tuple[int, int, int] = (255, 0, 0)) -> bytes:
    """A real, tiny, valid PNG — not just arbitrary bytes with a `.png`
    filename — so the round trip proves something about actual image
    uploads, not just opaque blobs."""
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), color).save(buf, format="PNG")
    return buf.getvalue()


def _patch_avatar(client: Client, token: str, png_bytes: bytes, **extra_fields):
    fields = {
        "avatar": SimpleUploadedFile("avatar.png", png_bytes, content_type="image/png"),
        **extra_fields,
    }
    body = encode_multipart(BOUNDARY, fields)
    return client.patch(
        f"{BASE_USERS}/profile/me", data=body, content_type=MULTIPART_CONTENT, **_auth(token),
    )


# ── the happy path ───────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_avatar_round_trip_happy_path(shared_storage, user):
    """PATCH profile/me with a real PNG -> avatar_url is a
    /api/media/v1/files/...?sig=&exp= URL -> GET that URL with NO
    Authorization header -> byte-identical PNG comes back. This is the
    whole point: a browser <img src> must work without headers."""
    token = _token(user)
    png = _png_bytes()

    resp = _patch_avatar(Client(), token, png)
    assert resp.status_code == 200
    body = resp.json()

    avatar_url = body["avatar_url"]
    assert avatar_url == body["avatarUrl"]
    assert avatar_url.startswith(f"/api/media/v1/files/avatars/{user.id}/")
    assert "?sig=" in avatar_url
    assert "&exp=" in avatar_url

    # avatar_payload() consistency (task requirement 1b): our own key shape
    # never matches the FastAPI source's UUID-only _FILE_ID_RE, so this
    # degrades to the legacy/external-URL branch — documented in
    # profile_service.avatar_payload's docstring, asserted here too so a
    # regression in either module shows up as a round-trip failure.
    assert body["avatar"] == {"id": None, "url": avatar_url, "variants": {}}

    user.refresh_from_db()
    assert user.avatar_url == avatar_url

    # The point: no Authorization header at all.
    get_resp = Client().get(avatar_url)
    assert get_resp.status_code == 200
    assert get_resp.content == png


# ── tampered / expired / wrong-key signatures ───────────────────────────────


@pytest.mark.django_db
def test_avatar_tampered_signature_rejected(shared_storage, user):
    token = _token(user)
    resp = _patch_avatar(Client(), token, _png_bytes())
    avatar_url = resp.json()["avatarUrl"]

    path_part, _, query_part = avatar_url.partition("?")
    sig_part, _, exp_part = query_part.partition("&")
    assert sig_part.startswith("sig=")
    sig_value = sig_part.removeprefix("sig=")
    tampered_sig = sig_value[:-1] + ("X" if sig_value[-1] != "X" else "Y")
    tampered_url = f"{path_part}?sig={tampered_sig}&{exp_part}"
    assert tampered_url != avatar_url

    get_resp = Client().get(tampered_url)
    # serve_raw_key: sig present but invalid -> 403 (distinct from the
    # 401 it returns when sig/exp are missing entirely).
    assert get_resp.status_code == 403


@pytest.mark.django_db
def test_avatar_expired_signature_rejected(shared_storage, user):
    token = _token(user)
    resp = _patch_avatar(Client(), token, _png_bytes())
    avatar_url = resp.json()["avatarUrl"]
    path_part, _, _ = avatar_url.partition("?")
    key = path_part.removeprefix("/api/media/v1/files/")

    # A validly-*computed* signature for an exp already in the past — proves
    # verify()'s time check rejects it, not just a garbage signature.
    expired_exp = int(time.time()) - 3600
    sig = _digest(key, expired_exp)
    expired_url = f"{path_part}?sig={sig}&exp={expired_exp}"

    get_resp = Client().get(expired_url)
    assert get_resp.status_code == 403


@pytest.mark.django_db
def test_avatar_signature_bound_to_its_own_key(shared_storage, user):
    """A valid signature minted for user A's avatar key must NOT verify
    against user B's avatar key — proves the signature is bound to the key,
    not just "any recent signature we issued"."""
    token_a = _token(user)
    resp_a = _patch_avatar(Client(), token_a, _png_bytes((255, 0, 0)))
    url_a = resp_a.json()["avatarUrl"]
    path_a, _, query_a = url_a.partition("?")

    user_b = _make_user("avatarowner2")
    token_b = _token(user_b)
    resp_b = _patch_avatar(Client(), token_b, _png_bytes((0, 255, 0)))
    url_b = resp_b.json()["avatarUrl"]
    path_b, _, _ = url_b.partition("?")

    assert path_a != path_b

    mixed_url = f"{path_b}?{query_a}"  # B's key, A's signature
    get_resp = Client().get(mixed_url)
    assert get_resp.status_code == 403

    # Sanity: B's own signature on B's own key still works fine.
    get_resp_b = Client().get(url_b)
    assert get_resp_b.status_code == 200
    assert get_resp_b.content == _png_bytes((0, 255, 0))


# ── replace ───────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_avatar_replace_serves_new_bytes(shared_storage, user):
    token = _token(user)
    png1 = _png_bytes((255, 0, 0))
    resp1 = _patch_avatar(Client(), token, png1)
    url1 = resp1.json()["avatarUrl"]

    png2 = _png_bytes((0, 0, 255))
    resp2 = _patch_avatar(Client(), token, png2)
    url2 = resp2.json()["avatarUrl"]

    assert url2 != url1
    user.refresh_from_db()
    assert user.avatar_url == url2

    get2 = Client().get(url2)
    assert get2.status_code == 200
    assert get2.content == png2


@pytest.mark.django_db
def test_avatar_replace_does_not_delete_previous_object(shared_storage, user):
    """``profile_service.save_avatar`` (read the code) never calls
    ``delete_avatar_object`` on the PREVIOUS ``avatar_url`` before
    overwriting it with the new one — ``_update_profile`` in
    ``apps/users/views.py`` just does ``user.avatar_url =
    profile_service.save_avatar(...)`` with no delete step first. So the old
    object is an orphan: still physically present in storage, and still
    served if its (still-unexpired) old signed URL is fetched again. This is
    a genuine finding, not a bug this task introduces — asserted here so a
    future change to add cleanup-on-replace shows up as an intentional test
    update, not a silent behaviour change."""
    token = _token(user)
    png1 = _png_bytes((255, 0, 0))
    resp1 = _patch_avatar(Client(), token, png1)
    url1 = resp1.json()["avatarUrl"]

    png2 = _png_bytes((0, 0, 255))
    _patch_avatar(Client(), token, png2)

    get1 = Client().get(url1)
    assert get1.status_code == 200  # NOT 404 -- the old object was never deleted
    assert get1.content == png1


# ── DELETE profile/avatar ────────────────────────────────────────────────────


@pytest.mark.django_db
def test_delete_avatar_clears_url_and_actually_removes_the_stored_object(shared_storage, user):
    """Unlike replace, ``remove_avatar`` (apps/users/views.py) DOES call
    ``profile_service.delete_avatar_object`` before clearing
    ``avatar_url`` -- so, unlike the replace case above, the underlying
    object really is gone afterwards (its old signed URL 404s)."""
    token = _token(user)
    resp = _patch_avatar(Client(), token, _png_bytes())
    avatar_url = resp.json()["avatarUrl"]

    del_resp = Client().delete(f"{BASE_USERS}/profile/avatar", **_auth(token))
    assert del_resp.status_code == 204

    user.refresh_from_db()
    assert user.avatar_url is None

    profile_resp = Client().get(f"{BASE_USERS}/profile/me", **_auth(token))
    assert profile_resp.status_code == 200
    assert profile_resp.json()["avatar_url"] is None

    get_resp = Client().get(avatar_url)
    assert get_resp.status_code == 404


# ── degradation when media is disabled ──────────────────────────────────────


@pytest.mark.django_db
def test_profile_patch_with_avatar_still_succeeds_when_media_disabled(shared_storage, user):
    """2.3 made avatar saving fire-and-forget and writes straight to
    ``htqweb.storage`` — no HTTP call into ``apps.media_files`` at all
    (decision Р3). ``ServiceGateMiddleware`` only intercepts requests whose
    PATH starts with ``/api/media/`` (``PREFIX_TO_SERVICE`` in
    ``apps/core/services.py`` — actually ``htqweb/middleware/
    service_gate.py``); a profile PATCH to ``/api/users/...`` is never
    routed through that prefix, so the gate never even runs for this
    request. That means: a direct ``htqweb.storage`` write (this one) is
    NOT covered by the media kill-switch at all -- the switch is purely
    HTTP-level, gating requests to media's OWN routes, not arbitrary
    in-process storage calls other apps make. That is a genuine
    (documented, not accidental) finding: disabling `media` in the registry
    does not stop `users` from writing new avatar objects into the shared
    bucket."""
    ServiceStatus.objects.update_or_create(app_label="media", defaults={"enabled": False})

    token = _token(user)
    resp = _patch_avatar(Client(), token, _png_bytes(), bio="media is down, still fine")
    assert resp.status_code == 200
    body = resp.json()
    assert body["bio"] == "media is down, still fine"

    user.refresh_from_db()
    assert user.bio == "media is down, still fine"
    # The direct storage write bypasses the HTTP-level gate entirely.
    assert user.avatar_url is not None
    assert shared_storage.objects  # the object really was written


@pytest.mark.django_db
def test_serving_avatar_503_when_media_disabled_but_profile_still_loads(shared_storage, user):
    """The flip side: once media IS disabled, FETCHING the avatar URL is
    gated (``serve_raw_key`` lives under ``/api/media/...``, squarely inside
    the gated prefix) -- so the avatar image itself disappears (503) even
    though the profile it's attached to keeps loading fine. This is the
    graceful-degradation story the task asks to prove: media down =
    missing pictures, not a broken app."""
    token = _token(user)
    resp = _patch_avatar(Client(), token, _png_bytes())
    avatar_url = resp.json()["avatarUrl"]

    ServiceStatus.objects.update_or_create(app_label="media", defaults={"enabled": False})

    get_resp = Client().get(avatar_url)
    assert get_resp.status_code == 503
    body = get_resp.json()
    assert body["code"] == "service_disabled"
    assert body["service"] == "media"

    profile_resp = Client().get(f"{BASE_USERS}/profile/me", **_auth(token))
    assert profile_resp.status_code == 200
    assert profile_resp.json()["avatar_url"] == avatar_url
