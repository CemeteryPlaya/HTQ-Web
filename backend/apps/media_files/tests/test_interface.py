"""Tests for ``apps/media_files/interface.py`` (Task 3.4).

Covers the two cross-app entry points (``store_file``, ``get_file_url``):
correct shape, reuse of the real upload pipeline (variants/audit land the
same as the HTTP endpoint), unknown/malformed-id handling, and the
``require_service("media")`` guard raising ``ServiceDisabled`` when the app
is turned off — mirroring ``apps/users/tests/test_interface.py`` and
``apps/cms/tests/test_interface.py``.

Storage is mocked at the ``htqweb.storage`` boundary, same
``_RecordingStorage`` pattern as ``test_upload_api.py``/``test_serving_api
.py`` — no real S3/MinIO. ``interface.store_file`` drives ``upload_service
.upload_file_bytes`` (patched via ``upload_service.get_storage``) and, for
image scopes, ``tasks.make_variants`` (patched via ``tasks.get_storage``);
``interface.get_file_url``'s round-trip fetch goes through
``views.download_file`` (patched via ``views.get_storage``).
"""

from __future__ import annotations

import io
import uuid

import pytest
from django.test import Client
from PIL import Image

from apps.core.models import ServiceStatus
from apps.core.services import ServiceDisabled
from apps.media_files import interface, tasks, views
from apps.media_files.models import AuditLog, FileMetadata, FileVariant
from apps.media_files.services import upload_service
from htqweb.storage.signed_url import verify as verify_signature

BASE = "/api/media/v1/files"


class _RecordingStorage:
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
def fake_storage(monkeypatch):
    storage = _RecordingStorage()
    monkeypatch.setattr(upload_service, "get_storage", lambda bucket=None: storage)
    monkeypatch.setattr(tasks, "get_storage", lambda bucket=None: storage)
    monkeypatch.setattr(views, "get_storage", lambda bucket=None: storage)
    return storage


def _disable_media():
    ServiceStatus.objects.update_or_create(app_label="media", defaults={"enabled": False})


def _png_bytes(size=(64, 64), color=(10, 20, 30)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


# ── store_file ───────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_store_file_shape(fake_storage):
    result = interface.store_file(
        data=b"hello world", filename="notes.txt", mime="text/plain",
        scope="generic", owner_id=42,
    )

    assert isinstance(result, dict)
    for key in ("id", "url", "mime", "size", "is_public"):
        assert key in result
    assert result["mime"] == "text/plain"
    assert result["size"] == len(b"hello world")
    assert result["is_public"] is False
    assert result["url"] == f"{BASE}/{result['id']}"

    meta = FileMetadata.objects.get(id=uuid.UUID(result["id"]))
    assert meta.owner_id == 42
    assert fake_storage.exists(meta.path)


@pytest.mark.django_db
def test_store_file_returns_plain_dict_not_orm_object(fake_storage):
    result = interface.store_file(
        data=b"hi", filename="x.txt", mime="text/plain", scope="generic", owner_id=1,
    )
    assert not isinstance(result, FileMetadata)
    assert isinstance(result, dict)


@pytest.mark.django_db
def test_store_file_writes_audit_log(fake_storage):
    result = interface.store_file(
        data=b"hi", filename="x.txt", mime="text/plain", scope="generic", owner_id=7,
    )
    entry = AuditLog.objects.get(resource_id=result["id"])
    assert entry.action == "file_uploaded"
    assert entry.user_id == 7


@pytest.mark.django_db
def test_store_file_enqueues_variants_for_image_scope_with_variants(fake_storage):
    result = interface.store_file(
        data=_png_bytes(), filename="avatar.png", mime="image/png",
        scope="avatar", owner_id=3,
    )
    # CELERY_TASK_ALWAYS_EAGER runs make_variants.delay() inline in tests —
    # same as test_upload_api.py's upload-endpoint variant-enqueue coverage.
    variant_names = set(
        FileVariant.objects.filter(file_id=result["id"]).values_list("variant", flat=True)
    )
    assert variant_names == {"thumb_32", "thumb_96", "thumb_256"}
    assert set(result["variants"]) == {"thumb_32", "thumb_96", "thumb_256"}


@pytest.mark.django_db
def test_store_file_no_variants_for_generic_scope(fake_storage):
    result = interface.store_file(
        data=b"hi", filename="x.txt", mime="text/plain", scope="generic", owner_id=1,
    )
    assert result["variants"] == {}
    assert not FileVariant.objects.filter(file_id=result["id"]).exists()


@pytest.mark.django_db
def test_store_file_owner_id_may_be_none(fake_storage):
    result = interface.store_file(
        data=b"hi", filename="x.txt", mime="text/plain", scope="generic", owner_id=None,
    )
    assert result["owner_id"] is None


@pytest.mark.django_db
def test_store_file_raises_when_media_disabled(fake_storage):
    _disable_media()
    with pytest.raises(ServiceDisabled):
        interface.store_file(
            data=b"hi", filename="x.txt", mime="text/plain", scope="generic", owner_id=1,
        )
    assert not FileMetadata.objects.exists()


# ── get_file_url ─────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_get_file_url_public_file_is_plain(fake_storage):
    meta = FileMetadata.objects.create(
        path="p", original_filename="p.txt", size=1, mime="text/plain",
        is_public=True, kind="document", scope="generic",
    )
    url = interface.get_file_url(meta.id)
    assert url == f"{BASE}/{meta.id}"


@pytest.mark.django_db
def test_get_file_url_private_file_is_signed_and_fetchable(fake_storage):
    meta = FileMetadata.objects.create(
        path="p", original_filename="p.txt", size=5, mime="text/plain",
        is_public=False, kind="document", scope="generic",
    )
    fake_storage.save(meta.path, b"hello", "text/plain")

    url = interface.get_file_url(meta.id)
    assert url.startswith(f"{BASE}/{meta.id}?sig=")

    resp = Client().get(url)
    assert resp.status_code == 200
    assert resp.content == b"hello"


@pytest.mark.django_db
def test_get_file_url_signature_verifies_against_shared_helper(fake_storage):
    """Not just "the URL works" — assert the query params really are a
    valid htqweb.storage.signed_url signature for this resource, i.e.
    get_file_url did not roll its own scheme."""
    meta = FileMetadata.objects.create(
        path="p", original_filename="p.txt", size=1, mime="text/plain",
        is_public=False, kind="document", scope="generic",
    )
    url = interface.get_file_url(meta.id)
    query = url.split("?", 1)[1]
    params = dict(pair.split("=") for pair in query.split("&"))
    assert verify_signature(str(meta.id), params["sig"], int(params["exp"]))


@pytest.mark.django_db
def test_get_file_url_accepts_str_or_uuid_id(fake_storage):
    meta = FileMetadata.objects.create(
        path="p", original_filename="p.txt", size=1, mime="text/plain",
        is_public=True, kind="document", scope="generic",
    )
    assert interface.get_file_url(meta.id) == interface.get_file_url(str(meta.id))


@pytest.mark.django_db
def test_get_file_url_unknown_id_returns_none(fake_storage):
    assert interface.get_file_url(uuid.uuid4()) is None


@pytest.mark.django_db
def test_get_file_url_malformed_id_returns_none(fake_storage):
    assert interface.get_file_url("not-a-uuid") is None


@pytest.mark.django_db
def test_get_file_url_soft_deleted_file_returns_none(fake_storage):
    import datetime

    meta = FileMetadata.objects.create(
        path="p", original_filename="p.txt", size=1, mime="text/plain",
        is_public=True, kind="document", scope="generic",
        deleted_at=datetime.datetime.now(datetime.timezone.utc),
    )
    assert interface.get_file_url(meta.id) is None


@pytest.mark.django_db
def test_get_file_url_raises_when_media_disabled(fake_storage):
    meta = FileMetadata.objects.create(
        path="p", original_filename="p.txt", size=1, mime="text/plain",
        is_public=True, kind="document", scope="generic",
    )
    _disable_media()
    with pytest.raises(ServiceDisabled):
        interface.get_file_url(meta.id)
