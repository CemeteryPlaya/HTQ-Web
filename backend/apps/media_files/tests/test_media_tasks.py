"""Tests for the two new media Celery tasks (``apps/media_files/tasks.py``):
``purge_soft_deleted`` and ``cleanup_orphan_files`` (Task 3.4).

Ported from ``services/media/app/workers/actors.py``. Tasks are called
DIRECTLY (not through ``.delay(...)``) to assert the ``ServiceDisabled``
guard — same style as ``apps/cms/tests/test_cms_tasks.py`` /
``apps/core/tests/test_celery.py::test_guarded_task_refuses_when_disabled``.

Storage is stubbed at the ``htqweb.storage`` boundary (patched into
``apps.media_files.tasks``, the only module this code imports
``get_storage`` into) — no network, no MinIO.
"""

from __future__ import annotations

import datetime

import pytest
from django.test import override_settings
from django.utils import timezone

from apps.core.models import ServiceStatus
from apps.core.services import ServiceDisabled
from apps.media_files import tasks
from apps.media_files.models import FileMetadata, FileVariant


class _RecordingStorage:
    def __init__(self):
        self.objects: dict[str, bytes] = {}
        self.deleted: list[str] = []

    def save(self, path, data, content_type=None):
        self.objects[path] = data

    def open(self, path, byte_range=None):
        return self.objects[path]

    def delete(self, path):
        self.deleted.append(path)
        self.objects.pop(path, None)

    def exists(self, path):
        return path in self.objects

    def size(self, path):
        return len(self.objects[path])


class _BoomOnDeleteStorage(_RecordingStorage):
    def delete(self, path):
        self.deleted.append(path)
        raise RuntimeError("bucket unreachable")


@pytest.fixture
def fake_storage(monkeypatch):
    storage = _RecordingStorage()
    monkeypatch.setattr(tasks, "get_storage", lambda bucket=None: storage)
    return storage


def _disable_media():
    ServiceStatus.objects.update_or_create(app_label="media", defaults={"enabled": False})


def _make_deleted(*, days_ago: float, path="a/original.png") -> FileMetadata:
    meta = FileMetadata.objects.create(
        path=path, original_filename="x.png", size=1, mime="image/png",
        is_public=False, kind="image", scope="generic",
    )
    meta.deleted_at = timezone.now() - datetime.timedelta(days=days_ago)
    meta.save(update_fields=["deleted_at"])
    return meta


# ── require_service guards ───────────────────────────────────────────────────


@pytest.mark.django_db
def test_purge_soft_deleted_refuses_when_media_disabled(fake_storage):
    _disable_media()
    with pytest.raises(ServiceDisabled):
        tasks.purge_soft_deleted()


@pytest.mark.django_db
def test_cleanup_orphan_files_refuses_when_media_disabled():
    _disable_media()
    with pytest.raises(ServiceDisabled):
        tasks.cleanup_orphan_files()


# ── purge_soft_deleted: matches the source's criteria ────────────────────────


@pytest.mark.django_db
@override_settings(MEDIA_SOFT_DELETE_GRACE_DAYS=30)
def test_purge_soft_deleted_removes_rows_past_grace_period(fake_storage):
    meta = _make_deleted(days_ago=31, path="a/2026/07/x/original.png")
    fake_storage.save(meta.path, b"bytes")

    purged = tasks.purge_soft_deleted()

    assert purged == 1
    assert not FileMetadata.objects.filter(id=meta.id).exists()
    assert not fake_storage.exists(meta.path)


@pytest.mark.django_db
@override_settings(MEDIA_SOFT_DELETE_GRACE_DAYS=30)
def test_purge_soft_deleted_leaves_rows_within_grace_period(fake_storage):
    meta = _make_deleted(days_ago=5)
    fake_storage.save(meta.path, b"bytes")

    purged = tasks.purge_soft_deleted()

    assert purged == 0
    assert FileMetadata.objects.filter(id=meta.id).exists()
    assert fake_storage.exists(meta.path)


@pytest.mark.django_db
@override_settings(MEDIA_SOFT_DELETE_GRACE_DAYS=30)
def test_purge_soft_deleted_ignores_rows_not_deleted_at_all(fake_storage):
    meta = FileMetadata.objects.create(
        path="never/deleted.png", original_filename="x.png", size=1,
        mime="image/png", is_public=False, kind="image", scope="generic",
    )
    fake_storage.save(meta.path, b"bytes")

    purged = tasks.purge_soft_deleted()

    assert purged == 0
    assert FileMetadata.objects.filter(id=meta.id).exists()


@pytest.mark.django_db
@override_settings(MEDIA_SOFT_DELETE_GRACE_DAYS=30)
def test_purge_soft_deleted_drops_variant_storage_objects_too(fake_storage):
    meta = _make_deleted(days_ago=31, path="a/2026/07/x/original.png")
    fake_storage.save(meta.path, b"orig")
    variant = FileVariant.objects.create(
        file=meta, variant="thumb_32", path="a/2026/07/x/thumb_32.webp",
        size=1, mime="image/webp", width=32, height=32,
    )
    fake_storage.save(variant.path, b"thumb")

    purged = tasks.purge_soft_deleted()

    assert purged == 1
    assert not fake_storage.exists(meta.path)
    assert not fake_storage.exists(variant.path)
    assert not FileVariant.objects.filter(id=variant.id).exists()


@pytest.mark.django_db
@override_settings(MEDIA_SOFT_DELETE_GRACE_DAYS=30)
def test_purge_soft_deleted_no_matching_rows_returns_zero_and_no_storage_call(fake_storage):
    assert tasks.purge_soft_deleted() == 0
    assert fake_storage.deleted == []


@pytest.mark.django_db
@override_settings(MEDIA_SOFT_DELETE_GRACE_DAYS=30)
def test_purge_soft_deleted_keeps_going_after_a_storage_error(monkeypatch):
    boom = _BoomOnDeleteStorage()
    monkeypatch.setattr(tasks, "get_storage", lambda bucket=None: boom)

    meta = _make_deleted(days_ago=31, path="a/original.png")

    # Storage.delete() raising must not abort the sweep — the DB row is
    # still reaped (best-effort contract, same as the source).
    purged = tasks.purge_soft_deleted()

    assert purged == 1
    assert not FileMetadata.objects.filter(id=meta.id).exists()
    assert boom.deleted == [meta.path]


@pytest.mark.django_db
@override_settings(MEDIA_SOFT_DELETE_GRACE_DAYS=10)
def test_purge_soft_deleted_grace_period_is_settings_driven(fake_storage):
    meta = _make_deleted(days_ago=11)
    fake_storage.save(meta.path, b"bytes")

    assert tasks.purge_soft_deleted() == 1
    assert not FileMetadata.objects.filter(id=meta.id).exists()


# ── cleanup_orphan_files: no-op, matches the (unimplemented) source ─────────


@pytest.mark.django_db
def test_cleanup_orphan_files_is_a_noop_and_touches_nothing(fake_storage):
    meta = FileMetadata.objects.create(
        path="untouched.png", original_filename="x.png", size=1,
        mime="image/png", is_public=True, kind="image", scope="generic",
    )
    fake_storage.save(meta.path, b"bytes")

    result = tasks.cleanup_orphan_files()

    assert result is None
    assert FileMetadata.objects.filter(id=meta.id).exists()
    assert fake_storage.exists(meta.path)
