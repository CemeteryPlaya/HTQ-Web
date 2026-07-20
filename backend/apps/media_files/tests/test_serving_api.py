"""Contract tests for file SERVING (task 3.3): download with Range/ETag,
variant download, signed URLs, list.

Mirrors ``services/media/app/api/v1/files.py``'s ``download_file`` /
``download_variant`` / ``issue_signed_url`` / ``list_files`` behaviourally
(same statuses for Range edge cases: 206/416/400; same 401-vs-403 split for
private access; same ETag shapes). Also covers the Django-specific raw
storage-key flow (``serve_raw_key``) that closes out task 2.3's avatar URL
(see ``apps/media_files/views.py``'s module docstring for why it exists).

Storage is mocked at the ``htqweb.storage`` boundary (same
``_RecordingStorage`` pattern as ``test_upload_api.py``'s ``fake_storage``),
patched into ``apps.media_files.views`` (the only module this task's code
imports ``get_storage`` into).
"""

from __future__ import annotations

import datetime
import time
import uuid

import pytest
from django.test import Client, override_settings

from apps.media_files import views
from apps.media_files.models import FileMetadata, FileVariant
from apps.users.models import User, UserStatus
from htqweb.authn.jwt import issue_token_pair
from htqweb.storage.signed_url import sign, signed_query

BASE = "/api/media/v1/files"

CONTENT = b"0123456789"  # 10 bytes, deliberately small + easy to slice


class _RecordingStorage:
    def __init__(self):
        self.objects: dict[str, tuple[bytes, str | None]] = {}
        self.presigned_calls: list[str] = []

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

    def presigned_get_url(self, path, ttl=None):
        self.presigned_calls.append(path)
        return f"https://minio.test/htqweb-media/{path}?presigned=1"


@pytest.fixture
def fake_storage(monkeypatch):
    storage = _RecordingStorage()
    monkeypatch.setattr(views, "get_storage", lambda bucket=None: storage)
    return storage


@pytest.fixture
def owner(db):
    u = User.objects.create(
        username="owner", email="owner@htq.test", password="x", status=UserStatus.ACTIVE
    )
    u.set_password("S3cret!")
    u.save()
    return u


@pytest.fixture
def other_user(db):
    u = User.objects.create(
        username="other", email="other@htq.test", password="x", status=UserStatus.ACTIVE
    )
    u.set_password("S3cret!")
    u.save()
    return u


@pytest.fixture
def admin(db):
    u = User.objects.create(
        username="admin", email="admin@htq.test", password="x", status=UserStatus.ACTIVE,
        is_staff=True,
    )
    u.set_password("S3cret!")
    u.save()
    return u


def _auth(user) -> dict:
    token = issue_token_pair(user)["access"]
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


def _make_file(*, owner_id, is_public, path="generic/2026/07/abc/original.txt",
                mime="text/plain", size=len(CONTENT)) -> FileMetadata:
    return FileMetadata.objects.create(
        path=path,
        original_filename="notes.txt",
        owner_id=owner_id,
        size=size,
        mime=mime,
        is_public=is_public,
        kind="document",
        scope="generic",
    )


# ─── public / private access control ────────────────────────────────────────


@pytest.mark.django_db
def test_public_file_served_without_auth(fake_storage, owner):
    meta = _make_file(owner_id=owner.id, is_public=True)
    fake_storage.save(meta.path, CONTENT, "text/plain")

    resp = Client().get(f"{BASE}/{meta.id}")

    assert resp.status_code == 200
    assert resp.content == CONTENT
    assert resp["Accept-Ranges"] == "bytes"
    assert resp["ETag"] == f'"{meta.id}-{meta.updated_at.timestamp()}"'


@pytest.mark.django_db
def test_private_file_no_auth_no_signature_is_401(fake_storage, owner):
    meta = _make_file(owner_id=owner.id, is_public=False)
    fake_storage.save(meta.path, CONTENT, "text/plain")

    resp = Client().get(f"{BASE}/{meta.id}")
    assert resp.status_code == 401


@pytest.mark.django_db
def test_private_file_wrong_user_jwt_is_403(fake_storage, owner, other_user):
    meta = _make_file(owner_id=owner.id, is_public=False)
    fake_storage.save(meta.path, CONTENT, "text/plain")

    resp = Client().get(f"{BASE}/{meta.id}", **_auth(other_user))
    assert resp.status_code == 403


@pytest.mark.django_db
def test_private_file_owner_jwt_is_served(fake_storage, owner):
    meta = _make_file(owner_id=owner.id, is_public=False)
    fake_storage.save(meta.path, CONTENT, "text/plain")

    resp = Client().get(f"{BASE}/{meta.id}", **_auth(owner))
    assert resp.status_code == 200
    assert resp.content == CONTENT


@pytest.mark.django_db
def test_private_file_admin_jwt_is_served(fake_storage, owner, admin):
    meta = _make_file(owner_id=owner.id, is_public=False)
    fake_storage.save(meta.path, CONTENT, "text/plain")

    resp = Client().get(f"{BASE}/{meta.id}", **_auth(admin))
    assert resp.status_code == 200


@pytest.mark.django_db
def test_private_file_valid_signature_is_served(fake_storage, owner):
    meta = _make_file(owner_id=owner.id, is_public=False)
    fake_storage.save(meta.path, CONTENT, "text/plain")

    sig, exp = sign(str(meta.id))
    resp = Client().get(f"{BASE}/{meta.id}?sig={sig}&exp={exp}")
    assert resp.status_code == 200
    assert resp.content == CONTENT


@pytest.mark.django_db
def test_private_file_tampered_signature_no_jwt_is_401(fake_storage, owner):
    # Matches the source's exact branch order: invalid sig falls through to
    # `_can_access_private(user, meta)` (False, no user) then
    # `elif user is None: 401` — a bad signature with no JWT at all is
    # indistinguishable from "not authenticated", not "forbidden".
    meta = _make_file(owner_id=owner.id, is_public=False)
    fake_storage.save(meta.path, CONTENT, "text/plain")

    sig, exp = sign(str(meta.id))
    resp = Client().get(f"{BASE}/{meta.id}?sig={sig}tampered&exp={exp}")
    assert resp.status_code == 401


@pytest.mark.django_db
def test_private_file_tampered_signature_with_wrong_jwt_is_403(fake_storage, owner, other_user):
    meta = _make_file(owner_id=owner.id, is_public=False)
    fake_storage.save(meta.path, CONTENT, "text/plain")

    sig, exp = sign(str(meta.id))
    resp = Client().get(
        f"{BASE}/{meta.id}?sig={sig}tampered&exp={exp}", **_auth(other_user)
    )
    assert resp.status_code == 403


@pytest.mark.django_db
def test_private_file_expired_signature_no_jwt_is_401(fake_storage, owner):
    meta = _make_file(owner_id=owner.id, is_public=False)
    fake_storage.save(meta.path, CONTENT, "text/plain")

    sig, exp = sign(str(meta.id), ttl=1)
    time.sleep(1.2)
    resp = Client().get(f"{BASE}/{meta.id}?sig={sig}&exp={exp}")
    assert resp.status_code == 401


@pytest.mark.django_db
def test_soft_deleted_file_not_served(fake_storage, owner):
    meta = _make_file(owner_id=owner.id, is_public=True)
    fake_storage.save(meta.path, CONTENT, "text/plain")
    meta.deleted_at = datetime.datetime.now(datetime.timezone.utc)
    meta.save(update_fields=["deleted_at"])

    resp = Client().get(f"{BASE}/{meta.id}", **_auth(owner))
    assert resp.status_code == 404


@pytest.mark.django_db
def test_unknown_file_id_is_404(fake_storage):
    resp = Client().get(f"{BASE}/{uuid.uuid4()}")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_file_physically_missing_is_404(fake_storage, owner):
    meta = _make_file(owner_id=owner.id, is_public=True)
    # deliberately never saved into fake_storage
    resp = Client().get(f"{BASE}/{meta.id}")
    assert resp.status_code == 404


# ─── Content-Disposition hardening (R4, stored-XSS) ─────────────────────────
#
# Pre-R4 both download_file and download_variant answered `Content-
# Disposition: inline` unconditionally. A `generic`/`chat`-scope upload with
# `is_public=true` and an attacker-controlled mime (`text/html`,
# `image/svg+xml`) would then render as live HTML/script on the app's own
# origin when fetched directly — stored XSS. These tests prove the fix: only
# an allow-list of mimes (raster images, pdf, video/audio) stays inline;
# everything else, including SVG (which can carry <script> despite the
# `image/` prefix), is forced to `attachment`.


@pytest.mark.django_db
def test_html_mime_file_served_as_attachment_not_inline(fake_storage, owner):
    meta = _make_file(owner_id=owner.id, is_public=True, mime="text/html")
    fake_storage.save(meta.path, CONTENT, "text/html")

    resp = Client().get(f"{BASE}/{meta.id}")

    assert resp.status_code == 200
    assert resp["Content-Disposition"].startswith("attachment")


@pytest.mark.django_db
def test_svg_mime_file_served_as_attachment_not_inline(fake_storage, owner):
    # image/svg+xml matches the "image/" prefix but can embed <script> —
    # must be explicitly denylisted, not swept up by the raster-image rule.
    meta = _make_file(owner_id=owner.id, is_public=True, mime="image/svg+xml")
    fake_storage.save(meta.path, CONTENT, "image/svg+xml")

    resp = Client().get(f"{BASE}/{meta.id}")

    assert resp.status_code == 200
    assert resp["Content-Disposition"].startswith("attachment")


@pytest.mark.django_db
def test_raster_image_file_still_served_inline(fake_storage, owner):
    # Regression guard: real images (avatars, news covers) must stay inline
    # or <img src> breaks.
    meta = _make_file(owner_id=owner.id, is_public=True, mime="image/jpeg")
    fake_storage.save(meta.path, CONTENT, "image/jpeg")

    resp = Client().get(f"{BASE}/{meta.id}")

    assert resp.status_code == 200
    assert resp["Content-Disposition"].startswith("inline")


@pytest.mark.django_db
def test_pdf_file_still_served_inline(fake_storage, owner):
    meta = _make_file(owner_id=owner.id, is_public=True, mime="application/pdf")
    fake_storage.save(meta.path, CONTENT, "application/pdf")

    resp = Client().get(f"{BASE}/{meta.id}")

    assert resp.status_code == 200
    assert resp["Content-Disposition"].startswith("inline")


def test_disposition_for_parameterized_svg_mime_is_attachment():
    """R6 Fix 5: a parameterized mime (``"image/svg+xml; charset=utf-8"``)
    must not slip past the exact-string SVG denylist check just because it
    still matches the ``image/`` prefix. Not currently reachable via the API
    (Django strips ``;``-params before storage) — hardened defensively at
    the ``_disposition_for`` unit level regardless."""
    assert views._disposition_for("image/svg+xml; charset=utf-8") == "attachment"
    assert views._disposition_for("IMAGE/SVG+XML") == "attachment"


@pytest.mark.django_db
def test_variant_download_html_mime_is_attachment(fake_storage, owner):
    # Variants are always images produced by the pipeline in practice, but
    # the serving path applies the same allow-list defensively.
    meta = _make_file(owner_id=owner.id, is_public=True, mime="image/png")
    fake_storage.save(meta.path, CONTENT, "image/png")
    fv = FileVariant.objects.create(
        file=meta, variant="thumb_96", path="generic/2026/07/abc/thumb_96.html",
        mime="text/html", size=len(CONTENT), width=96, height=96,
    )
    fake_storage.save(fv.path, CONTENT, "text/html")

    resp = Client().get(f"{BASE}/{meta.id}/thumb_96")

    assert resp.status_code == 200
    assert resp["Content-Disposition"].startswith("attachment")


@pytest.mark.django_db
def test_variant_download_image_mime_stays_inline(fake_storage, owner):
    meta = _make_file(owner_id=owner.id, is_public=True, mime="image/png")
    fake_storage.save(meta.path, CONTENT, "image/png")
    fv = FileVariant.objects.create(
        file=meta, variant="thumb_96", path="generic/2026/07/abc/thumb_96.jpg",
        mime="image/jpeg", size=len(CONTENT), width=96, height=96,
    )
    fake_storage.save(fv.path, CONTENT, "image/jpeg")

    resp = Client().get(f"{BASE}/{meta.id}/thumb_96")

    assert resp.status_code == 200
    assert resp["Content-Disposition"].startswith("inline")


# ─── Range support ───────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_range_partial_returns_206_with_exact_slice(fake_storage, owner):
    meta = _make_file(owner_id=owner.id, is_public=True)
    fake_storage.save(meta.path, CONTENT, "text/plain")

    resp = Client().get(f"{BASE}/{meta.id}", HTTP_RANGE="bytes=0-4")
    assert resp.status_code == 206
    assert resp["Content-Range"] == f"bytes 0-4/{len(CONTENT)}"
    assert resp.content == CONTENT[0:5]
    assert len(resp.content) == 5


@pytest.mark.django_db
def test_range_open_ended_returns_206_correct_slice(fake_storage, owner):
    meta = _make_file(owner_id=owner.id, is_public=True)
    fake_storage.save(meta.path, CONTENT, "text/plain")

    resp = Client().get(f"{BASE}/{meta.id}", HTTP_RANGE="bytes=5-")
    assert resp.status_code == 206
    total = len(CONTENT)
    assert resp["Content-Range"] == f"bytes 5-{total - 1}/{total}"
    assert resp.content == CONTENT[5:]


@pytest.mark.django_db
def test_range_unsatisfiable_returns_416(fake_storage, owner):
    meta = _make_file(owner_id=owner.id, is_public=True)
    fake_storage.save(meta.path, CONTENT, "text/plain")

    resp = Client().get(f"{BASE}/{meta.id}", HTTP_RANGE="bytes=9999-10000")
    assert resp.status_code == 416
    assert resp["Content-Range"] == f"bytes */{len(CONTENT)}"


@pytest.mark.django_db
def test_range_malformed_returns_400(fake_storage, owner):
    meta = _make_file(owner_id=owner.id, is_public=True)
    fake_storage.save(meta.path, CONTENT, "text/plain")

    resp = Client().get(f"{BASE}/{meta.id}", HTTP_RANGE="bytes=abc")
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Invalid Range Header"


# ─── variant download ────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_variant_served_with_its_own_etag(fake_storage, owner):
    meta = _make_file(owner_id=owner.id, is_public=True, mime="image/png")
    variant_bytes = b"thumbnail-bytes"
    fv = FileVariant.objects.create(
        file=meta, variant="thumb_32", path=f"{meta.path.rsplit('/', 1)[0]}/thumb_32.webp",
        size=len(variant_bytes), mime="image/webp", width=32, height=32,
    )
    fake_storage.save(fv.path, variant_bytes, "image/webp")

    resp = Client().get(f"{BASE}/{meta.id}/thumb_32")
    assert resp.status_code == 200
    assert resp.content == variant_bytes
    assert resp["ETag"] == f'"{fv.id}"'
    assert resp["ETag"] != f'"{meta.id}-{meta.updated_at.timestamp()}"'


@pytest.mark.django_db
def test_unknown_variant_is_404(fake_storage, owner):
    meta = _make_file(owner_id=owner.id, is_public=True, mime="image/png")
    resp = Client().get(f"{BASE}/{meta.id}/thumb_999")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_private_variant_requires_access_same_as_original(fake_storage, owner, other_user):
    meta = _make_file(owner_id=owner.id, is_public=False, mime="image/png")
    variant_bytes = b"thumb"
    fv = FileVariant.objects.create(
        file=meta, variant="thumb_32", path="x/thumb_32.webp",
        size=len(variant_bytes), mime="image/webp", width=32, height=32,
    )
    fake_storage.save(fv.path, variant_bytes, "image/webp")

    assert Client().get(f"{BASE}/{meta.id}/thumb_32").status_code == 401
    assert Client().get(
        f"{BASE}/{meta.id}/thumb_32", **_auth(other_user)
    ).status_code == 403
    assert Client().get(
        f"{BASE}/{meta.id}/thumb_32", **_auth(owner)
    ).status_code == 200


# ─── sign round-trip ─────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_sign_route_round_trips_to_a_working_url(fake_storage, owner):
    meta = _make_file(owner_id=owner.id, is_public=False)
    fake_storage.save(meta.path, CONTENT, "text/plain")

    resp = Client().post(f"{BASE}/{meta.id}/sign", **_auth(owner))
    assert resp.status_code == 200
    body = resp.json()
    assert body["url"].startswith(f"{BASE}/{meta.id}?sig=")
    assert "exp" in body

    fetch = Client().get(body["url"])
    assert fetch.status_code == 200
    assert fetch.content == CONTENT


@pytest.mark.django_db
def test_sign_route_for_variant_scopes_to_that_variant(fake_storage, owner):
    meta = _make_file(owner_id=owner.id, is_public=False, mime="image/png")
    variant_bytes = b"thumb"
    fv = FileVariant.objects.create(
        file=meta, variant="thumb_32", path="x2/thumb_32.webp",
        size=len(variant_bytes), mime="image/webp", width=32, height=32,
    )
    fake_storage.save(fv.path, variant_bytes, "image/webp")

    resp = Client().post(f"{BASE}/{meta.id}/sign?variant=thumb_32", **_auth(owner))
    assert resp.status_code == 200
    body = resp.json()
    assert body["url"].startswith(f"{BASE}/{meta.id}/thumb_32?sig=")

    fetch = Client().get(body["url"])
    assert fetch.status_code == 200
    assert fetch.content == variant_bytes

    # A signature minted for the variant must NOT also work for the original
    # (no JWT supplied either, so the source's branch order yields 401 —
    # same "invalid sig + no user" case as the tampered-signature test above).
    sig = body["url"].split("sig=")[1].split("&")[0]
    exp = body["url"].split("exp=")[1]
    forged = Client().get(f"{BASE}/{meta.id}?sig={sig}&exp={exp}")
    assert forged.status_code == 401


@pytest.mark.django_db
def test_sign_route_forbidden_for_non_owner(fake_storage, owner, other_user):
    meta = _make_file(owner_id=owner.id, is_public=False)
    resp = Client().post(f"{BASE}/{meta.id}/sign", **_auth(other_user))
    assert resp.status_code == 403


@pytest.mark.django_db
def test_sign_route_requires_auth(fake_storage, owner):
    meta = _make_file(owner_id=owner.id, is_public=False)
    resp = Client().post(f"{BASE}/{meta.id}/sign")
    assert resp.status_code == 401


# ─── list ─────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_list_files_requires_admin(fake_storage, owner):
    _make_file(owner_id=owner.id, is_public=True)
    resp = Client().get(f"{BASE}/", **_auth(owner))
    assert resp.status_code == 403


@pytest.mark.django_db
def test_list_files_admin_sees_all_excluding_soft_deleted(fake_storage, owner, admin):
    m1 = _make_file(owner_id=owner.id, is_public=True, path="a/1")
    m2 = _make_file(owner_id=owner.id, is_public=False, path="a/2")
    deleted = _make_file(owner_id=owner.id, is_public=True, path="a/3")
    deleted.deleted_at = datetime.datetime.now(datetime.timezone.utc)
    deleted.save(update_fields=["deleted_at"])

    resp = Client().get(f"{BASE}/", **_auth(admin))
    assert resp.status_code == 200
    ids = {row["id"] for row in resp.json()}
    assert ids == {str(m1.id), str(m2.id)}


@pytest.mark.django_db
def test_list_files_unauthenticated_is_401(fake_storage):
    resp = Client().get(f"{BASE}/")
    assert resp.status_code == 401


# ─── raw storage-key serving (avatar flow) ──────────────────────────────────


@pytest.mark.django_db
def test_raw_key_no_signature_is_401(fake_storage):
    key = "avatars/7/abc.jpg"
    fake_storage.save(key, CONTENT, "image/jpeg")
    resp = Client().get(f"{BASE}/{key}")
    assert resp.status_code == 401


@pytest.mark.django_db
def test_raw_key_tampered_signature_is_403(fake_storage):
    key = "avatars/7/abc.jpg"
    fake_storage.save(key, CONTENT, "image/jpeg")
    query = signed_query(key)
    resp = Client().get(f"{BASE}/{key}?{query}x")
    assert resp.status_code == 403


@pytest.mark.django_db
@override_settings(STORAGE_BACKEND="local")
def test_raw_key_valid_signature_local_backend_streams(fake_storage):
    key = "avatars/7/abc.jpg"
    fake_storage.save(key, CONTENT, "image/jpeg")
    query = signed_query(key)

    resp = Client().get(f"{BASE}/{key}?{query}")
    assert resp.status_code == 200
    assert resp.content == CONTENT


@pytest.mark.django_db
@override_settings(STORAGE_BACKEND="s3")
def test_raw_key_valid_signature_s3_backend_redirects(fake_storage):
    key = "avatars/7/abc.jpg"
    fake_storage.save(key, CONTENT, "image/jpeg")
    query = signed_query(key)

    resp = Client().get(f"{BASE}/{key}?{query}")
    assert resp.status_code == 302
    assert resp["Location"] == f"https://minio.test/htqweb-media/{key}?presigned=1"
    assert fake_storage.presigned_calls == [key]


@pytest.mark.django_db
def test_raw_key_missing_object_is_404(fake_storage):
    key = "avatars/7/missing.jpg"
    query = signed_query(key)
    resp = Client().get(f"{BASE}/{key}?{query}")
    assert resp.status_code == 404


# NOTE (final review of phases 2-3, Finding 2): this section used to include
# ``test_avatar_save_and_serve_end_to_end``, closing the loop between
# ``profile_service.save_avatar`` (which wrote a raw storage key + signed
# URL) and ``serve_raw_key`` above. Avatars no longer take that path —
# ``save_avatar`` now routes through ``apps.media_files.interface.
# store_file(scope="avatar", ...)``, so an avatar is a real ``FileMetadata``
# row served by ``download_file``/``download_variant`` like any other
# upload, never by ``serve_raw_key``. The users<->media avatar round-trip
# now lives in ``apps/users/tests/test_avatar_e2e.py``. The raw-key tests
# above remain as coverage for ``serve_raw_key`` itself, which is kept as
# general-purpose infrastructure (see ``views.py``'s module docstring).
