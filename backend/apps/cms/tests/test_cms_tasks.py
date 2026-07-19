"""Tests for the cms Celery tasks (``apps/cms/tasks.py``) and the news
snapshot service (``apps/cms/services/news_snapshot.py``).

Ported from ``services/cms/app/workers/actors.py`` (Dramatiq actors) and
``services/cms/app/services/news_snapshot.py``. Tasks are called DIRECTLY
(not through ``.delay(...)``) to assert the ``ServiceDisabled`` guard, same
style as ``apps/core/tests/test_celery.py::test_guarded_task_refuses_when_disabled``.

The snapshot tests stub storage at the ``htqweb.storage`` boundary by
passing a fake ``Storage``-shaped object into ``write_news_snapshot`` /
``delete_news_snapshot`` (both accept ``storage=`` overrides, same as the
FastAPI original) — no network, no MinIO. Assertions are against the keys
and payloads the logic COMPUTES, not merely "the fake received something".
"""

from __future__ import annotations

import json

import pytest
from django.test import override_settings

from apps.cms.models import News
from apps.cms.services import news_snapshot as snap
from apps.core.models import ServiceStatus
from apps.core.services import ServiceDisabled


# ── fake storage (records calls, no network) ────────────────────────────────


class FakeStorage:
    def __init__(self):
        self.saved: dict[str, tuple[bytes, str | None]] = {}
        self.deleted: list[str] = []

    def save(self, path, data, content_type=None):
        self.saved[path] = (data, content_type)

    def delete(self, path):
        self.deleted.append(path)

    def open(self, path, byte_range=None):  # pragma: no cover - unused here
        raise NotImplementedError

    def exists(self, path):  # pragma: no cover - unused here
        raise NotImplementedError

    def size(self, path):  # pragma: no cover - unused here
        raise NotImplementedError

    def presigned_get_url(self, path, ttl=None):  # pragma: no cover - unused here
        raise NotImplementedError


class BoomStorage(FakeStorage):
    def delete(self, path):
        raise RuntimeError("bucket unreachable")


def _disable_cms():
    ServiceStatus.objects.update_or_create(app_label="cms", defaults={"enabled": False})


# ── require_service guards ───────────────────────────────────────────────────


@pytest.mark.django_db
def test_translate_news_refuses_when_cms_disabled():
    from apps.cms.tasks import translate_news

    _disable_cms()
    with pytest.raises(ServiceDisabled):
        translate_news(1, "en")


@pytest.mark.django_db
def test_notify_admins_on_contact_request_refuses_when_cms_disabled():
    from apps.cms.tasks import notify_admins_on_contact_request

    _disable_cms()
    with pytest.raises(ServiceDisabled):
        notify_admins_on_contact_request(1)


@pytest.mark.django_db
def test_publish_scheduled_news_refuses_when_cms_disabled():
    from apps.cms.tasks import publish_scheduled_news

    _disable_cms()
    with pytest.raises(ServiceDisabled):
        publish_scheduled_news()


# ── translate_news: settings-gated no-op (network-free) ─────────────────────


@pytest.mark.django_db
@override_settings(TRANSLATION_API_KEY="")
def test_translate_news_noops_without_api_key():
    from apps.cms.tasks import translate_news

    # Must return cleanly with no exception and no network attempt.
    assert translate_news(1, "en") is None


# ── notify_admins_on_contact_request: settings-gated no-op (network-free) ───


@pytest.mark.django_db
@override_settings(EMAIL_SERVICE_URL="")
def test_notify_admins_noops_without_email_service_url():
    from apps.cms.tasks import notify_admins_on_contact_request

    assert notify_admins_on_contact_request(1) is None


# ── publish_scheduled_news: query semantics ported byte-identical ──────────


@pytest.mark.django_db
def test_publish_scheduled_news_publishes_due_rows_and_leaves_others():
    from django.utils import timezone

    from apps.cms.tasks import publish_scheduled_news

    due = News.objects.create(
        title="Due", slug="due", category="", status="draft", published=False,
    )
    due.published_at = timezone.now() - timezone.timedelta(minutes=1)
    due.save(update_fields=["published_at"])

    not_due = News.objects.create(
        title="Not due", slug="not-due", category="", status="draft", published=False,
    )
    not_due.published_at = timezone.now() + timezone.timedelta(hours=1)
    not_due.save(update_fields=["published_at"])

    already_published = News.objects.create(
        title="Already", slug="already", category="", status="published", published=True,
    )
    already_published.published_at = timezone.now() - timezone.timedelta(days=1)
    already_published.save(update_fields=["published_at"])

    no_published_at = News.objects.create(
        title="No date", slug="no-date", category="", status="draft", published=False,
    )

    updated = publish_scheduled_news()

    assert updated == 1
    due.refresh_from_db()
    not_due.refresh_from_db()
    no_published_at.refresh_from_db()
    assert due.published is True
    assert not_due.published is False
    assert no_published_at.published is False


# ── news_snapshot: key layout, byte-identical to the FastAPI original ───────


def test_news_prefix_matches_original_layout():
    assert snap.news_prefix(42) == "news/42"


def test_content_object_key_matches_original_layout():
    assert snap.content_object_key(42) == "news/42/content.md"


def test_metadata_object_key_matches_original_layout():
    assert snap.metadata_object_key(42) == "news/42/metadata.json"


@pytest.mark.django_db
def test_write_news_snapshot_writes_expected_keys_and_content():
    news = News.objects.create(
        title="Hello", slug="hello", category="general", content="# Body\ntext",
        summary="sum", image="news/1/cover.png", status="published", published=True,
    )
    news.published_at = news.created_at
    news.save(update_fields=["published_at"])

    storage = FakeStorage()
    snap.write_news_snapshot(news, storage=storage)

    assert set(storage.saved) == {
        f"news/{news.id}/content.md",
        f"news/{news.id}/metadata.json",
    }

    content_bytes, content_type = storage.saved[f"news/{news.id}/content.md"]
    assert content_bytes == "# Body\ntext".encode("utf-8")
    assert content_type == "text/markdown; charset=utf-8"

    metadata_bytes, metadata_type = storage.saved[f"news/{news.id}/metadata.json"]
    assert metadata_type == "application/json"
    metadata = json.loads(metadata_bytes)
    assert set(metadata) == {
        "id", "title", "slug", "summary", "category", "image",
        "published", "published_at", "created_at",
    }
    assert metadata["id"] == news.id
    assert metadata["title"] == "Hello"
    assert metadata["slug"] == "hello"
    assert metadata["summary"] == "sum"
    assert metadata["category"] == "general"
    assert metadata["image"] == "news/1/cover.png"
    assert metadata["published"] is True
    assert metadata["published_at"] == news.published_at.isoformat()
    assert metadata["created_at"] == news.created_at.isoformat()


@pytest.mark.django_db
def test_write_news_snapshot_handles_empty_content_and_null_image():
    news = News.objects.create(
        title="No body", slug="no-body", category="", content="",
        status="draft", published=False,
    )

    storage = FakeStorage()
    snap.write_news_snapshot(news, storage=storage)

    content_bytes, _ = storage.saved[f"news/{news.id}/content.md"]
    assert content_bytes == b""
    metadata = json.loads(storage.saved[f"news/{news.id}/metadata.json"][0])
    assert metadata["image"] is None
    assert metadata["published_at"] is None


@pytest.mark.django_db
def test_delete_news_snapshot_removes_content_and_metadata_keys():
    storage = FakeStorage()
    snap.delete_news_snapshot(7, storage=storage)
    assert storage.deleted == ["news/7/content.md", "news/7/metadata.json"]


@pytest.mark.django_db
def test_delete_news_snapshot_is_best_effort_and_swallows_storage_errors():
    storage = BoomStorage()
    # Must not raise even though every delete() call blows up.
    snap.delete_news_snapshot(7, storage=storage)
