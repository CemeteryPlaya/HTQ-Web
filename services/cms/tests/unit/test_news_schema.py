"""Unit tests for CMS Pydantic schemas."""

import pytest
from pydantic import ValidationError

from app.schemas.news import NewsCreate, NewsRead, NewsUpdate


class TestNewsCreate:
    def test_valid_create(self):
        data = NewsCreate(title="Test", slug="test-slug", summary="Summary", content="Body")
        assert data.title == "Test"
        assert data.slug == "test-slug"

    def test_title_required(self):
        with pytest.raises(ValidationError):
            NewsCreate(slug="slug-only")

    def test_slug_required(self):
        with pytest.raises(ValidationError):
            NewsCreate(title="No slug")


class TestNewsUpdate:
    def test_partial_update(self):
        data = NewsUpdate(title="Updated")
        assert data.title == "Updated"
        dumped = data.model_dump(exclude_unset=True)
        assert "slug" not in dumped

    def test_empty_update_valid(self):
        data = NewsUpdate()
        assert data.model_dump(exclude_unset=True) == {}


class TestNewsRead:
    def test_from_dict(self):
        data = NewsRead(
            id=1,
            title="News",
            slug="news-1",
            summary="",
            content="",
            image=None,
            category="general",
            published=True,
            published_at="2026-01-01T00:00:00Z",
            created_at="2026-01-01T00:00:00Z",
        )
        assert data.id == 1
        assert data.published is True
