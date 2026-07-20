"""Contract tests for ``POST /api/media/v1/files/`` (task 3.2).

Mirrors ``services/media/app/api/v1/files.py::upload_file`` +
``app/services/media_service.py::upload_file_bytes`` behaviourally: same
scope-policy-driven ``is_public``/mime/size rules, same error statuses
(413 oversize, 415 bad mime), same variant-enqueue condition.

Storage is mocked at the ``htqweb.storage`` boundary (same pattern as
``apps/users/tests/test_profile_api.py``'s ``fake_storage`` fixture) — no
real S3/MinIO required. Both the view's pipeline (``upload_service``) and
the Celery task (``tasks``) import ``get_storage`` into their own module
namespace, so both need patching to share one fake backend.
"""

from __future__ import annotations

import io
import logging
import uuid

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from PIL import Image

from apps.media_files import tasks
from apps.media_files.models import AuditLog, FileMetadata, FileVariant
from apps.media_files.services import upload_service
from apps.users.models import User, UserStatus
from htqweb.authn.jwt import issue_token_pair

BASE = "/api/media/v1/files/"


# ─── fixtures ────────────────────────────────────────────────────────────────


class _RecordingStorage:
    def __init__(self):
        self.objects: dict[str, tuple[bytes, str | None]] = {}

    def save(self, path, data, content_type=None):
        self.objects[path] = (data, content_type)

    def open(self, path, byte_range=None):
        return self.objects[path][0]

    def delete(self, path):
        self.objects.pop(path, None)

    def exists(self, path):
        return path in self.objects

    def size(self, path):
        return len(self.objects[path][0])


@pytest.fixture
def fake_storage(monkeypatch):
    storage = _RecordingStorage()
    monkeypatch.setattr(upload_service, "get_storage", lambda bucket=None: storage)
    monkeypatch.setattr(tasks, "get_storage", lambda bucket=None: storage)
    return storage


@pytest.fixture
def user(db):
    u = User.objects.create(
        username="uploader", email="uploader@htq.test", password="x",
        status=UserStatus.ACTIVE,
    )
    u.set_password("S3cret!")
    u.save()
    return u


@pytest.fixture
def elevated_user(db):
    # R5 (decision Д1): hr_doc is a restricted scope now — writing to it
    # requires is_elevated. The mime/signature-validation tests below exist
    # to exercise upload_service's pipeline for that scope, not authorization
    # (see test_scope_authz.py for the authz coverage), so they upload as
    # this staff user rather than the plain `user` fixture.
    u = User.objects.create(
        username="hr-staffer", email="hr-staffer@htq.test", password="x",
        status=UserStatus.ACTIVE, is_staff=True,
    )
    u.set_password("S3cret!")
    u.save()
    return u


def _auth(user) -> dict:
    token = issue_token_pair(user)["access"]
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


def _png_bytes(size=(64, 64), color=(200, 30, 30)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def _upload(client, user, *, filename, content, content_type, scope=None, is_public=None):
    data = {"file": SimpleUploadedFile(filename, content, content_type=content_type)}
    if scope is not None:
        data["scope"] = scope
    if is_public is not None:
        data["is_public"] = is_public
    return client.post(BASE, data=data, **_auth(user))


# ─── happy paths ─────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_upload_avatar_scope_is_public_and_enqueues_variants(fake_storage, user):
    resp = _upload(
        Client(), user,
        filename="me.png", content=_png_bytes(), content_type="image/png",
        scope="avatar",
    )
    assert resp.status_code == 201
    body = resp.json()

    assert body["is_public"] is True
    assert body["kind"] == "image"
    assert body["scope"] == "avatar"
    assert body["sha256"] and len(body["sha256"]) == 64
    assert body["width"] == 64 and body["height"] == 64

    meta = FileMetadata.objects.get(id=uuid.UUID(body["id"]))
    assert meta.is_public is True
    assert meta.kind == "image"
    assert meta.owner_id == user.id
    assert fake_storage.exists(meta.path)

    # avatar policy variants: thumb_32, thumb_96, thumb_256 — CELERY_TASK_ALWAYS_EAGER
    # runs make_variants.delay() inline, so rows exist by the time we return.
    variant_names = set(
        FileVariant.objects.filter(file_id=meta.id).values_list("variant", flat=True)
    )
    assert variant_names == {"thumb_32", "thumb_96", "thumb_256"}
    assert set(body["variants"]) == {"thumb_32", "thumb_96", "thumb_256"}
    for v in FileVariant.objects.filter(file_id=meta.id):
        assert fake_storage.exists(v.path)

    entry = AuditLog.objects.get(resource_id=str(meta.id))
    assert entry.action == "file_uploaded"
    assert entry.user_id == user.id


@pytest.mark.django_db
def test_upload_news_scope_is_public_with_preview_variants(fake_storage, user):
    resp = _upload(
        Client(), user,
        filename="cover.png", content=_png_bytes((300, 200)), content_type="image/png",
        scope="news",
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["is_public"] is True
    assert body["scope"] == "news"

    meta = FileMetadata.objects.get(id=uuid.UUID(body["id"]))
    variant_names = set(
        FileVariant.objects.filter(file_id=meta.id).values_list("variant", flat=True)
    )
    assert variant_names == {"thumb_256", "preview_1024"}


@pytest.mark.django_db
def test_upload_generic_scope_default_is_private_no_variants(fake_storage, user):
    resp = _upload(
        Client(), user,
        filename="notes.txt", content=b"hello world", content_type="text/plain",
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["is_public"] is False
    assert body["scope"] == "generic"
    assert body["kind"] == "other"
    assert body["variants"] == {}

    meta = FileMetadata.objects.get(id=uuid.UUID(body["id"]))
    assert not FileVariant.objects.filter(file_id=meta.id).exists()


@pytest.mark.django_db
def test_upload_audit_write_failure_is_non_fatal(fake_storage, user, monkeypatch, caplog):
    """Consistency fix (R3 review, Finding 4): the ``FileMetadata`` row is
    already committed by the time ``audit.record_action`` runs — an
    audit-insert failure must not 500 an already-successful upload. Mirrors
    ``apps.users.tests.test_audit.
    test_admin_create_user_audit_write_failure_is_non_fatal``: force
    ``AuditLog.objects.create`` to raise, do the real upload over HTTP, and
    assert the endpoint still returns 201, the file still persisted, and the
    failure was logged rather than swallowed silently.
    """

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated audit DB failure")

    monkeypatch.setattr(AuditLog.objects, "create", _boom)

    with caplog.at_level(logging.ERROR, logger="apps.media_files.services.audit"):
        resp = _upload(
            Client(), user,
            filename="notes.txt", content=b"hello world", content_type="text/plain",
        )

    assert resp.status_code == 201
    body = resp.json()
    assert FileMetadata.objects.filter(id=uuid.UUID(body["id"])).exists()
    assert not AuditLog.objects.filter(action="file_uploaded").exists()
    assert any(
        "audit record_action failed" in record.getMessage()
        for record in caplog.records
    )


@pytest.mark.django_db
def test_upload_unknown_scope_falls_back_to_generic_policy(fake_storage, user):
    resp = _upload(
        Client(), user,
        filename="notes.txt", content=b"hello world", content_type="text/plain",
        scope="not-a-real-scope",
    )
    assert resp.status_code == 201
    body = resp.json()
    # Behaviour (is_public/variants) follows the generic fallback even though
    # the raw scope string is preserved on the row (matches the FastAPI
    # source: `meta.scope = scope`, unconstrained at the DB layer).
    assert body["is_public"] is False
    assert body["scope"] == "not-a-real-scope"
    assert body["variants"] == {}


# ─── validation errors ────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_oversize_file_for_scope_returns_413(fake_storage, user):
    oversized = b"x" * (9 * 1024 * 1024)  # avatar cap is 8 MB
    resp = _upload(
        Client(), user,
        filename="big.png", content=oversized, content_type="image/png",
        scope="avatar",
    )
    assert resp.status_code == 413
    assert "8 MB" in resp.json()["detail"]
    assert not FileMetadata.objects.exists()


@pytest.mark.django_db
def test_wrong_mime_for_restricted_scope_returns_415(fake_storage, elevated_user):
    # hr_doc only allows application/pdf; send a PNG.
    resp = _upload(
        Client(), elevated_user,
        filename="not-a-doc.png", content=_png_bytes(), content_type="image/png",
        scope="hr_doc",
    )
    assert resp.status_code == 415
    assert not FileMetadata.objects.exists()


@pytest.mark.django_db
def test_hr_doc_scope_accepts_pdf_and_stores_privately_with_no_variants(fake_storage, elevated_user):
    resp = _upload(
        Client(), elevated_user,
        filename="handbook.pdf", content=b"%PDF-1.4 minimal test bytes",
        content_type="application/pdf", scope="hr_doc",
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["is_public"] is False
    assert body["kind"] == "document"
    assert body["variants"] == {}


@pytest.mark.django_db
def test_hr_doc_scope_rejects_spoofed_pdf_content_type(fake_storage, elevated_user):
    # Attack case (security review, task 3.2 finding): declared Content-Type
    # is application/pdf but the bytes are a shell script — since detect_mime
    # doesn't run real magic-byte detection (python-magic segfaults on this
    # host) and hr_doc is a document kind (no Pillow decode-verify path
    # either), only the magic-byte signature check in
    # upload_service._validate_signature stands between this and storage.
    resp = _upload(
        Client(), elevated_user,
        filename="handbook.pdf", content=b"#!/bin/sh\nrm -rf /",
        content_type="application/pdf", scope="hr_doc",
    )
    assert resp.status_code == 415
    assert not FileMetadata.objects.exists()


@pytest.mark.django_db
def test_hr_doc_scope_rejects_html_masquerading_as_pdf(fake_storage, elevated_user):
    resp = _upload(
        Client(), elevated_user,
        filename="handbook.pdf", content=b"<html><body>not a pdf</body></html>",
        content_type="application/pdf", scope="hr_doc",
    )
    assert resp.status_code == 415
    assert not FileMetadata.objects.exists()


@pytest.mark.django_db
def test_hr_doc_scope_accepts_genuine_pdf_signature(fake_storage, elevated_user):
    resp = _upload(
        Client(), elevated_user,
        filename="handbook.pdf", content=b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\nminimal filler bytes",
        content_type="application/pdf", scope="hr_doc",
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["kind"] == "document"
    assert FileMetadata.objects.filter(id=uuid.UUID(body["id"])).exists()


@pytest.mark.django_db
def test_image_scope_still_works_end_to_end_after_signature_check(fake_storage, user):
    # Regression guard: the new signature check must not break the normal
    # avatar/news image path (Pillow's decode-verify still does the heavy
    # lifting there; the signature check is uniform but redundant for images).
    resp = _upload(
        Client(), user,
        filename="me.png", content=_png_bytes(), content_type="image/png",
        scope="avatar",
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["kind"] == "image"
    assert FileMetadata.objects.filter(id=uuid.UUID(body["id"])).exists()


@pytest.mark.django_db
def test_permissive_scope_accepts_unverifiable_mime(fake_storage, user):
    # chat allows any mime (policy.mimes == ()); a mime with no known
    # signature must not be blocked just because it can't be verified.
    resp = _upload(
        Client(), user,
        filename="thing.bin", content=b"arbitrary bytes, no known signature",
        content_type="application/vnd.custom", scope="chat",
    )
    assert resp.status_code == 201
    body = resp.json()
    assert FileMetadata.objects.filter(id=uuid.UUID(body["id"])).exists()


@pytest.mark.django_db
def test_unauthenticated_upload_returns_401(fake_storage, user):
    resp = Client().post(
        BASE,
        data={"file": SimpleUploadedFile("x.png", _png_bytes(), content_type="image/png")},
    )
    assert resp.status_code == 401
    assert not FileMetadata.objects.exists()


# ─── variant enqueue plumbing ─────────────────────────────────────────────────


@pytest.mark.django_db
def test_variants_delay_called_only_for_scope_with_variants(fake_storage, user, monkeypatch):
    calls = []
    monkeypatch.setattr(
        tasks.make_variants, "delay", lambda file_id: calls.append(file_id)
    )

    _upload(
        Client(), user,
        filename="avatar.png", content=_png_bytes(), content_type="image/png",
        scope="avatar",
    )
    assert len(calls) == 1

    _upload(
        Client(), user,
        filename="notes.txt", content=b"hi", content_type="text/plain",
    )
    assert len(calls) == 1  # generic scope has no variants configured — not enqueued


@pytest.mark.django_db
def test_broker_failure_on_enqueue_does_not_fail_the_upload(fake_storage, user, monkeypatch):
    def _boom(file_id):
        raise RuntimeError("broker unreachable")

    monkeypatch.setattr(tasks.make_variants, "delay", _boom)

    resp = _upload(
        Client(), user,
        filename="avatar.png", content=_png_bytes(), content_type="image/png",
        scope="avatar",
    )
    assert resp.status_code == 201
    body = resp.json()
    assert FileMetadata.objects.filter(id=uuid.UUID(body["id"])).exists()
