"""Cross-app end-to-end round-trip: users' profile-avatar upload -> media's
serving (task 3.5), re-verified against the final review of phases 2-3.

These tests legitimately straddle two apps and are deliberately placed here
(in ``apps.users.tests``, not ``apps.media_files.tests``) because the
user-facing flow starts in ``users`` — an authenticated ``PATCH
profile/me`` — and only crosses into ``media`` at the point where the
browser follows the ``avatar_url`` it got back.

**What changed here (final review of phases 2-3, Findings 1 & 2) and why
these tests had to be rewritten, not just patched:**

- Finding 2 routed ``profile_service.save_avatar`` through
  ``apps.media_files.interface.store_file(scope="avatar", ...)`` — the real
  upload pipeline — instead of a direct ``htqweb.storage`` write. An avatar
  is now a genuine ``FileMetadata`` row: it must decode as a real image
  (Pillow), and it is served by ``apps.media_files.views.download_file``
  (Range/ETag/access-control, task 3.3), NOT by ``serve_raw_key`` (the
  raw-storage-key endpoint task 3.3 originally added *specifically* to make
  the old direct-write scheme's URLs fetchable — see that view's updated
  module docstring). So the storage double here patches the pipeline's
  actual boundary (``upload_service``/``tasks``), not
  ``profile_service``/``media_views`` directly, and every uploaded avatar
  in these tests must be real, decodable PNG bytes.
- Finding 1 stopped persisting a signed (self-expiring) URL in
  ``User.avatar_url`` — it stores the bare, unsigned canonical path now,
  and ``profile_service.avatar_payload``/``build_response`` mint a fresh
  URL on every response via ``apps.media_files.interface.get_file_url``.
  The ``avatar`` scope (``apps.media_files.services.scope_policy``) is
  ``public=True``, so in practice avatar URLs are never signed at all any
  more (a public ``FileMetadata`` serves with no signature, see
  ``download_file``) — the old tampered/expired/cross-key-signature tests
  that exercised the raw-key HMAC flow no longer apply to avatars and are
  replaced by ``test_avatar_url_survives_past_the_original_ttl_even_if_the_
  file_were_private`` below, which forces a FileMetadata row private to
  prove the read-time re-signing mechanism itself still works (that
  coverage would otherwise be lost entirely now that the happy path never
  touches ``sign()``/``verify()`` for avatars).
"""

from __future__ import annotations

import io

import pytest
from django.conf import settings
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.test.client import BOUNDARY, MULTIPART_CONTENT, encode_multipart
from PIL import Image

from apps.core.models import ServiceStatus
from apps.media_files import tasks as media_tasks
from apps.media_files import views as media_views
from apps.media_files.models import FileMetadata
from apps.media_files.services import upload_service as media_upload_service
from apps.users.models import User, UserStatus
from htqweb.authn.jwt import issue_token_pair

BASE_USERS = "/api/users/v1"


class _RecordingStorage:
    """Minimal in-memory ``htqweb.storage.Storage`` double patched into the
    upload pipeline's actual storage boundary (``upload_service`` writes
    the original, ``tasks.make_variants`` — run eagerly, see
    ``CELERY_TASK_ALWAYS_EAGER`` in test settings — reads it back to
    produce thumbnails), so a write from one is visible to a read from the
    other, same shared-bucket contract the real S3 setup gives both in
    production."""

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


@pytest.fixture
def shared_storage(monkeypatch):
    """One in-memory storage shared by the WRITE and the READ side.

    Each module imports ``get_storage`` into its own namespace, so patching the
    write side alone leaves the serving views reading the real backend — the
    object is absent there and ``download_file`` answers 404 "File physically
    missing". The whole point of this module is the round-trip, so the views
    module has to be patched too (same as ``media_files/tests/test_serving_api.py``).
    """
    storage = _RecordingStorage()
    monkeypatch.setattr(media_upload_service, "get_storage", lambda bucket=None: storage)
    monkeypatch.setattr(media_tasks, "get_storage", lambda bucket=None: storage)
    monkeypatch.setattr(media_views, "get_storage", lambda bucket=None: storage)
    return storage


def _disable_media():
    ServiceStatus.objects.update_or_create(app_label="media", defaults={"enabled": False})


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
    filename. The real pipeline (Finding 2) runs Pillow's decoder on
    upload, so opaque blobs are now rejected (415) rather than accepted —
    this proves something about actual image uploads."""
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), color).save(buf, format="PNG")
    return buf.getvalue()


def _decoded_size(image_bytes: bytes) -> tuple[int, int]:
    """Pixel dimensions of a served image, decoded fresh (no assumption
    about which format it's actually in)."""
    img = Image.open(io.BytesIO(image_bytes))
    img.load()
    return img.size


def _avg_color(image_bytes: bytes) -> tuple[float, float, float]:
    """Mean (r, g, b) over every pixel of a served image.

    Used instead of byte-equality to the originally-uploaded PNG: the real
    pipeline (``apps.media_files.services.image_service.normalise``, final
    review of phases 2-3, Finding 2) re-encodes every upload on the way in
    — an alpha-less RGB PNG (exactly what ``_png_bytes`` produces)
    collapses to JPEG — so the served bytes are *never* byte-identical to
    what was uploaded, by design, not a bug. Our fixtures are flat
    single-color squares, so even through JPEG's lossy quantization the
    average color still lands close enough to the original solid color to
    tell two colors apart reliably at an 8x8 size / default quality.
    """
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    pixels = list(img.getdata())
    n = len(pixels)
    return (
        sum(p[0] for p in pixels) / n,
        sum(p[1] for p in pixels) / n,
        sum(p[2] for p in pixels) / n,
    )


def _patch_avatar(client: Client, token: str, png_bytes: bytes, **extra_fields):
    fields = {
        "avatar": SimpleUploadedFile("avatar.png", png_bytes, content_type="image/png"),
        **extra_fields,
    }
    body = encode_multipart(BOUNDARY, fields)
    return client.patch(
        f"{BASE_USERS}/profile/me", data=body, content_type=MULTIPART_CONTENT, **_auth(token),
    )


def _file_id_from_url(url: str) -> str:
    return url.removeprefix("/api/media/v1/files/").split("?", 1)[0]


# ── the happy path ───────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_avatar_round_trip_happy_path(shared_storage, user):
    """PATCH profile/me with a real PNG -> avatar_url is a
    /api/media/v1/files/<uuid> URL (public FileMetadata, so no ?sig=/&exp=
    at all — Finding 1) -> GET that URL with NO Authorization header ->
    byte-identical PNG comes back. This is the whole point: a browser
    <img src> must work without headers."""
    token = _token(user)
    png = _png_bytes()

    resp = _patch_avatar(Client(), token, png)
    assert resp.status_code == 200
    body = resp.json()

    avatar_url = body["avatar_url"]
    assert avatar_url == body["avatarUrl"]
    assert avatar_url.startswith("/api/media/v1/files/")
    assert "?" not in avatar_url  # public file — never signed (Finding 1)

    file_id = _file_id_from_url(avatar_url)
    meta = FileMetadata.objects.get(id=file_id)
    assert meta.owner_id == user.id
    assert meta.scope == "avatar"
    assert meta.is_public is True

    # Finding 2: avatars now go through the real pipeline, so the scope's
    # configured variants (thumb_32/96/256) are actually produced — the
    # structured `avatar` block is finally real, not a permanent {}.
    assert body["avatar"]["id"] == str(meta.id)
    assert set(body["avatar"]["variants"]) == {"thumb_32", "thumb_96", "thumb_256"}

    user.refresh_from_db()
    assert user.avatar_url == avatar_url

    # The point: no Authorization header at all.
    get_resp = Client().get(avatar_url)
    assert get_resp.status_code == 200
    # NOT `get_resp.content == png`: the real pipeline (Finding 2)
    # re-encodes on upload (image_service.normalise) — this alpha-less RGB
    # PNG collapses to JPEG, so the served bytes are a different byte
    # stream from what was uploaded by design, not a bug (see _avg_color's
    # docstring). What must still hold for the round trip to be considered
    # working: the response decodes as a real image, at the uploaded pixel
    # dimensions, and still recognizably the uploaded solid red.
    assert get_resp["Content-Type"] == "image/jpeg"
    assert _decoded_size(get_resp.content) == (8, 8)
    r, g, b = _avg_color(get_resp.content)
    assert r > 200 and g < 40 and b < 40


@pytest.mark.django_db
def test_avatar_variant_thumbnails_are_actually_served(shared_storage, user):
    """Direct proof that the variants in the `avatar` block aren't just
    well-formed URLs — they resolve to real, distinct thumbnail images
    (Finding 2's "variants can finally be real" follow-through)."""
    token = _token(user)
    resp = _patch_avatar(Client(), token, _png_bytes())
    avatar = resp.json()["avatar"]
    variants = avatar["variants"]
    assert variants  # non-empty: the pipeline really ran

    for name, url in variants.items():
        assert url.startswith(f"/api/media/v1/files/{avatar['id']}/{name}")
        get_resp = Client().get(url)
        assert get_resp.status_code == 200
        assert len(get_resp.content) > 0


# ── the CRITICAL regression test (Finding 1) ────────────────────────────────


@pytest.mark.django_db
def test_avatar_url_survives_past_the_original_ttl_even_if_the_file_were_private(
    shared_storage, user, monkeypatch,
):
    """THE regression test for Finding 1 (CRITICAL).

    The old code minted a signed URL ONCE, at upload time, and persisted
    the whole thing — signature and all — in ``User.avatar_url`` forever.
    Once ``settings.NEWS_SIGNED_URL_TTL`` (1h) elapsed, that baked-in
    signature stopped verifying and the avatar died permanently with no
    refresh path.

    The ``avatar`` scope happens to be ``public=True`` today, so a real
    avatar upload never actually needs a signature — testing only the
    happy path would pass trivially even if someone reintroduced the exact
    bug for a scope that isn't public. So this test forces the underlying
    ``FileMetadata`` row private after upload, which makes
    ``profile_service.avatar_payload`` (via
    ``apps.media_files.interface.get_file_url``) actually exercise
    ``sign()`` on every call — then jumps the HMAC clock well past the
    original TTL and proves a *freshly refetched* profile still hands back
    a currently-valid, working URL, distinct from the one issued at upload
    time.
    """
    from htqweb.storage import signed_url as signed_url_module

    token = _token(user)
    png = _png_bytes()
    resp = _patch_avatar(Client(), token, png)
    upload_url = resp.json()["avatarUrl"]
    assert "sig=" not in upload_url and "exp=" not in upload_url

    file_id = _file_id_from_url(upload_url)
    meta = FileMetadata.objects.get(id=file_id)
    meta.is_public = False
    meta.save(update_fields=["is_public"])

    class _FrozenClock:
        def __init__(self, t: float):
            self.t = t

        def time(self) -> float:
            return self.t

    real_now = signed_url_module.time.time()
    clock = _FrozenClock(real_now)
    monkeypatch.setattr(signed_url_module, "time", clock)

    # A signature minted "now" (t0) would already be dead at this point in
    # the OLD scheme's timeline — jump straight past where it would have
    # expired.
    clock.t = real_now + settings.NEWS_SIGNED_URL_TTL + 1000

    profile_resp = Client().get(f"{BASE_USERS}/profile/me", **_auth(token))
    assert profile_resp.status_code == 200
    fresh_url = profile_resp.json()["avatarUrl"]
    assert "sig=" in fresh_url  # now private -> genuinely signed
    assert fresh_url != upload_url  # a NEW signature, not a stale echo

    get_resp = Client().get(fresh_url)
    assert get_resp.status_code == 200
    # NOT byte-equality with `png` — see _avg_color's docstring: the
    # pipeline re-encodes this alpha-less PNG to JPEG on upload, so the
    # served bytes were never going to match the original upload
    # byte-for-byte. What this test is actually about (the signature
    # surviving past the original TTL) is proven by status_code == 200 and
    # `fresh_url != upload_url` above; here we only need the served bytes
    # to still be the SAME underlying image, not corrupted by the
    # re-signing path.
    assert _decoded_size(get_resp.content) == (8, 8)
    r, g, b = _avg_color(get_resp.content)
    assert r > 200 and g < 40 and b < 40


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
    # NOT byte-equality with `png2` — see _avg_color's docstring (re-encode
    # to JPEG on upload). The property this test is actually about —
    # replacement serves the NEW image, not the old one — is proven by
    # decoding the response and checking it's recognizably blue (png2's
    # color), not red (png1's).
    assert _decoded_size(get2.content) == (8, 8)
    r, g, b = _avg_color(get2.content)
    assert b > 200 and r < 40 and g < 40


@pytest.mark.django_db
def test_avatar_replace_soft_deletes_previous_object(shared_storage, user):
    """R4 (orphan cleanup): ``_update_profile`` (``apps/users/views.py``)
    now soft-deletes the PREVIOUS avatar's ``FileMetadata`` row (via
    ``profile_service.delete_avatar_object`` ->
    ``apps.media_files.interface.delete_file``, same mechanism
    ``remove_avatar`` already used) once the new avatar has landed. Before
    R4, the old row was left forever as an orphan — this replaces
    ``test_avatar_replace_does_not_delete_previous_object``, which asserted
    exactly that (now-fixed) gap."""
    token = _token(user)
    png1 = _png_bytes((255, 0, 0))
    resp1 = _patch_avatar(Client(), token, png1)
    url1 = resp1.json()["avatarUrl"]
    file_id1 = _file_id_from_url(url1)

    png2 = _png_bytes((0, 0, 255))
    resp2 = _patch_avatar(Client(), token, png2)
    url2 = resp2.json()["avatarUrl"]
    file_id2 = _file_id_from_url(url2)

    meta1 = FileMetadata.objects.get(id=file_id1)
    assert meta1.deleted_at is not None  # old avatar soft-deleted

    meta2 = FileMetadata.objects.get(id=file_id2)
    assert meta2.deleted_at is None  # new avatar stays live

    # The soft-deleted old file follows the same serving rule as any other
    # soft-deleted FileMetadata (test_serving_api.py's
    # test_soft_deleted_file_not_served): 404, not the old bytes.
    get1 = Client().get(url1)
    assert get1.status_code == 404

    get2 = Client().get(url2)
    assert get2.status_code == 200
    assert _decoded_size(get2.content) == (8, 8)
    r, g, b = _avg_color(get2.content)
    assert b > 200 and r < 40 and g < 40


@pytest.mark.django_db
def test_avatar_replace_cleanup_failure_does_not_fail_the_patch(shared_storage, user, monkeypatch):
    """Degradation: if soft-deleting the OLD avatar blows up (media
    unreachable, or any other hiccup), the profile PATCH must still
    succeed — the NEW avatar is already stored and set by that point, only
    the old orphan's cleanup is best-effort. Force the failure directly at
    ``profile_service.delete_avatar_object`` (the call site
    ``_update_profile`` uses) rather than relying on it already swallowing
    exceptions internally, so this test would catch a regression even if
    that internal try/except were ever removed."""
    token = _token(user)
    _patch_avatar(Client(), token, _png_bytes((255, 0, 0)))

    from apps.users import views as users_views

    def _boom(_avatar_url):
        raise RuntimeError("media unreachable")

    monkeypatch.setattr(users_views.profile_service, "delete_avatar_object", _boom)

    resp2 = _patch_avatar(Client(), token, _png_bytes((0, 0, 255)))
    assert resp2.status_code == 200
    body = resp2.json()
    assert body["avatarUrl"] is not None

    user.refresh_from_db()
    assert user.avatar_url == body["avatarUrl"]


# ── DELETE profile/avatar ────────────────────────────────────────────────────


@pytest.mark.django_db
def test_delete_avatar_clears_url_and_soft_deletes_the_underlying_file(shared_storage, user):
    """Unlike replace, ``remove_avatar`` (apps/users/views.py) DOES call
    ``profile_service.delete_avatar_object`` before clearing
    ``avatar_url`` — since Finding 2, that soft-deletes the
    ``FileMetadata`` row via ``apps.media_files.interface.delete_file``
    (no direct storage access from ``users`` any more). Observable effect
    is the same as before: the old URL 404s afterwards."""
    token = _token(user)
    resp = _patch_avatar(Client(), token, _png_bytes())
    avatar_url = resp.json()["avatarUrl"]
    file_id = _file_id_from_url(avatar_url)

    del_resp = Client().delete(f"{BASE_USERS}/profile/avatar", **_auth(token))
    assert del_resp.status_code == 204

    user.refresh_from_db()
    assert user.avatar_url is None

    profile_resp = Client().get(f"{BASE_USERS}/profile/me", **_auth(token))
    assert profile_resp.status_code == 200
    assert profile_resp.json()["avatar_url"] is None

    meta = FileMetadata.objects.get(id=file_id)
    assert meta.deleted_at is not None

    get_resp = Client().get(avatar_url)
    assert get_resp.status_code == 404


# ── degradation when media is disabled (Finding 2's kill-switch half) ──────


@pytest.mark.django_db
def test_profile_patch_with_avatar_still_succeeds_when_media_disabled(shared_storage, user):
    """Finding 2 closed the kill-switch hole: before this fix, disabling
    ``media`` did NOT stop ``users`` from writing new avatar objects into
    the shared bucket (the direct ``htqweb.storage`` write bypassed
    ``require_service`` entirely — a documented, genuine gap). Now
    ``save_avatar`` calls ``apps.media_files.interface.store_file``, whose
    first statement is ``require_service("media")`` — so a disabled
    ``media`` correctly refuses the write (``ServiceDisabled``), and the
    degradation contract from task 2.3 still holds: the rest of the PATCH
    (fields already applied) must land with 200, the old avatar_url (None,
    here) is left untouched, and the failure is logged, not raised."""
    ServiceStatus.objects.update_or_create(app_label="media", defaults={"enabled": False})

    token = _token(user)
    resp = _patch_avatar(Client(), token, _png_bytes(), bio="media is down, still fine")
    assert resp.status_code == 200
    body = resp.json()
    assert body["bio"] == "media is down, still fine"

    user.refresh_from_db()
    assert user.bio == "media is down, still fine"
    # The fix: the kill-switch now actually stops the write.
    assert user.avatar_url is None
    assert not FileMetadata.objects.exists()


@pytest.mark.django_db
def test_serving_avatar_gets_503_when_media_disabled_but_profile_still_loads(shared_storage, user):
    """The flip side: once an avatar exists and media IS THEN disabled,
    FETCHING it is gated (``download_file`` lives under ``/api/media/...``,
    squarely inside ``ServiceGateMiddleware``'s gated prefix) — so the
    avatar image itself disappears (503) even though the profile it's
    attached to keeps loading fine (``avatar_payload`` catches the
    ``ServiceDisabled`` from ``get_file_url`` and falls back to the stored,
    already-unsigned path rather than failing the whole response). This is
    the graceful-degradation story: media down = missing pictures, not a
    broken app."""
    token = _token(user)
    resp = _patch_avatar(Client(), token, _png_bytes())
    avatar_url = resp.json()["avatarUrl"]

    ServiceStatus.objects.update_or_create(app_label="media", defaults={"enabled": False})
    # The upload above already warmed apps.core.services.service_status()'s
    # 5s cache to "media enabled" (store_file/get_file_url both call
    # require_service("media") while building the PATCH response). A raw
    # ORM update_or_create — unlike a real flip through
    # apps.core.admin.ServiceStatusAdmin.save_model, which busts this same
    # key on every save — does not invalidate that cache, so the very next
    # request within the 5s TTL would still see the stale "enabled" value
    # and this test would false-negative (200 instead of 503) regardless of
    # whether the gate itself works. Bust it by hand, exactly like
    # test_admin_gate.py's
    # test_disabled_service_denies_add_change_delete_at_modeladmin_level
    # does for the same reason.
    cache.delete("svc-status:media")

    get_resp = Client().get(avatar_url)
    assert get_resp.status_code == 503
    body = get_resp.json()
    assert body["code"] == "service_disabled"
    assert body["service"] == "media"

    profile_resp = Client().get(f"{BASE_USERS}/profile/me", **_auth(token))
    assert profile_resp.status_code == 200
    assert profile_resp.json()["avatar_url"] == avatar_url
