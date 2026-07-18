"""Integration tests for News API endpoints."""

import pytest

from tests.conftest import admin_headers, user_headers


@pytest.mark.asyncio
async def test_create_news_admin(client):
    resp = await client.post(
        "/api/cms/v1/news/",
        json={
            "title": "Breaking News",
            "slug": "breaking-news",
            "summary": "Summary",
            "content": "Full content",
            "category": "general",
            "published": True,
        },
        headers=admin_headers(),
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["title"] == "Breaking News"
    assert data["slug"] == "breaking-news"
    assert data["published"] is True
    assert data["published_at"] is not None  # auto-set


@pytest.mark.asyncio
async def test_create_news_non_admin_forbidden(client):
    resp = await client.post(
        "/api/cms/v1/news/",
        json={"title": "Fail", "slug": "fail"},
        headers=user_headers(),
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_create_news_unauthenticated(client):
    resp = await client.post(
        "/api/cms/v1/news/",
        json={"title": "Fail", "slug": "fail"},
    )
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_list_news_public_only_published(client):
    # Create published and unpublished
    await client.post(
        "/api/cms/v1/news/",
        json={"title": "Pub", "slug": "pub-1", "published": True},
        headers=admin_headers(),
    )
    await client.post(
        "/api/cms/v1/news/",
        json={"title": "Draft", "slug": "draft-1", "published": False},
        headers=admin_headers(),
    )

    # Public (no auth) should only see published
    resp = await client.get("/api/cms/v1/news/")
    assert resp.status_code == 200
    slugs = [n["slug"] for n in resp.json()]
    assert "pub-1" in slugs
    assert "draft-1" not in slugs


@pytest.mark.asyncio
async def test_list_news_admin_sees_all(client):
    resp = await client.get("/api/cms/v1/news/", headers=admin_headers())
    assert resp.status_code == 200
    # Admin sees both published and unpublished
    data = resp.json()
    assert isinstance(data, list)


@pytest.mark.asyncio
async def test_get_news_by_id(client):
    create_resp = await client.post(
        "/api/cms/v1/news/",
        json={"title": "By ID", "slug": "by-id", "published": True},
        headers=admin_headers(),
    )
    news_id = create_resp.json()["id"]

    resp = await client.get(f"/api/cms/v1/news/{news_id}")
    assert resp.status_code == 200
    assert resp.json()["slug"] == "by-id"


@pytest.mark.asyncio
async def test_get_unpublished_news_public_404(client):
    create_resp = await client.post(
        "/api/cms/v1/news/",
        json={"title": "Hidden", "slug": "hidden", "published": False},
        headers=admin_headers(),
    )
    news_id = create_resp.json()["id"]

    resp = await client.get(f"/api/cms/v1/news/{news_id}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_update_news(client):
    create_resp = await client.post(
        "/api/cms/v1/news/",
        json={"title": "Original", "slug": "upd-1", "published": True},
        headers=admin_headers(),
    )
    news_id = create_resp.json()["id"]

    resp = await client.patch(
        f"/api/cms/v1/news/{news_id}",
        json={"title": "Updated Title"},
        headers=admin_headers(),
    )
    assert resp.status_code == 200
    assert resp.json()["title"] == "Updated Title"


@pytest.mark.asyncio
async def test_delete_news(client):
    create_resp = await client.post(
        "/api/cms/v1/news/",
        json={"title": "To Delete", "slug": "del-1", "published": True},
        headers=admin_headers(),
    )
    news_id = create_resp.json()["id"]

    resp = await client.delete(f"/api/cms/v1/news/{news_id}", headers=admin_headers())
    assert resp.status_code == 204

    resp = await client.get(f"/api/cms/v1/news/{news_id}", headers=admin_headers())
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_filter_by_category(client):
    await client.post(
        "/api/cms/v1/news/",
        json={"title": "Tech", "slug": "cat-tech", "category": "tech", "published": True},
        headers=admin_headers(),
    )
    await client.post(
        "/api/cms/v1/news/",
        json={"title": "Sports", "slug": "cat-sports", "category": "sports", "published": True},
        headers=admin_headers(),
    )

    resp = await client.get("/api/cms/v1/news/?category=tech")
    assert resp.status_code == 200
    data = resp.json()
    assert all(n["category"] == "tech" for n in data)


@pytest.mark.asyncio
async def test_pagination(client):
    for i in range(5):
        await client.post(
            "/api/cms/v1/news/",
            json={"title": f"Page {i}", "slug": f"page-{i}", "published": True},
            headers=admin_headers(),
        )

    resp = await client.get("/api/cms/v1/news/?limit=2&offset=0")
    assert resp.status_code == 200
    assert len(resp.json()) <= 2


@pytest.mark.asyncio
async def test_slug_conflict(client):
    await client.post(
        "/api/cms/v1/news/",
        json={"title": "First", "slug": "conflict-slug", "published": True},
        headers=admin_headers(),
    )
    resp = await client.post(
        "/api/cms/v1/news/",
        json={"title": "Duplicate", "slug": "conflict-slug"},
        headers=admin_headers(),
    )
    assert resp.status_code == 409
