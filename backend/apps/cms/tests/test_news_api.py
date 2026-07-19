"""Contract tests for ``/api/cms/v1/news/*``.

Mirrors ``services/cms/app/api/v1/news.py``: public list/by-slug/detail with
visibility rules, admin create/update/delete. Tokens are built with real
``jwt.encode`` against ``settings.JWT_SECRET`` — same style as
``test_contact_requests_api.py``.
"""

import json
from datetime import timedelta

import jwt as pyjwt
import pytest
from django.conf import settings
from django.test import Client
from django.utils import timezone

from apps.cms.models import AuditLog, Category, News, Tag

BASE = "/api/cms/v1"


def _token(**over):
    claims = {
        "user_id": 7, "username": "u", "email": "u@htq.test",
        "is_staff": False, "is_superuser": False, "is_admin": False,
        "token_type": "access", "iat": 1, "exp": 9_999_999_999,
        "iss": "htqweb-auth", "sub": "7",
        **over,
    }
    return pyjwt.encode(claims, settings.JWT_SECRET, algorithm="HS256")


def _admin_token(**over):
    return _token(user_id=9, sub="9", is_admin=True, **over)


def _auth_header(token: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


def _post_json(client: Client, path: str, body: dict, **extra):
    return client.post(path, data=json.dumps(body), content_type="application/json", **extra)


def _patch_json(client: Client, path: str, body: dict, **extra):
    return client.patch(path, data=json.dumps(body), content_type="application/json", **extra)


def _make_news(**over) -> News:
    defaults = dict(title="T", slug="t", status="published")
    defaults.update(over)
    return News.objects.create(**defaults)


# ── GET /news/ — public list, visibility rules ──────────────────────────────


@pytest.mark.django_db
def test_list_news_public_no_token_200():
    _make_news(slug="a", status="published")
    resp = Client().get(f"{BASE}/news/")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"items", "page", "page_size", "total", "has_next"}
    assert body["page"] == 1
    assert body["page_size"] == 12
    assert body["total"] == 1
    assert body["has_next"] is False
    assert body["items"][0]["slug"] == "a"


@pytest.mark.django_db
def test_list_news_hides_draft_from_anonymous():
    _make_news(slug="draft-post", status="draft")
    resp = Client().get(f"{BASE}/news/")
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


@pytest.mark.django_db
def test_list_news_hides_future_scheduled_from_anonymous():
    _make_news(
        slug="future", status="scheduled",
        scheduled_at=timezone.now() + timedelta(days=1),
    )
    resp = Client().get(f"{BASE}/news/")
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


@pytest.mark.django_db
def test_list_news_shows_elapsed_scheduled_to_anonymous():
    _make_news(
        slug="live-now", status="scheduled",
        scheduled_at=timezone.now() - timedelta(minutes=1),
    )
    resp = Client().get(f"{BASE}/news/")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["slug"] == "live-now"


@pytest.mark.django_db
def test_list_news_hides_archived_from_anonymous():
    _make_news(slug="old", status="archived")
    resp = Client().get(f"{BASE}/news/")
    assert resp.json()["total"] == 0


@pytest.mark.django_db
def test_list_news_admin_token_sees_drafts():
    _make_news(slug="draft-post", status="draft")
    resp = Client().get(f"{BASE}/news/", **_auth_header(_admin_token()))
    assert resp.status_code == 200
    assert resp.json()["total"] == 1


@pytest.mark.django_db
def test_list_news_admin_status_filter():
    _make_news(slug="d1", status="draft")
    _make_news(slug="p1", status="published")
    resp = Client().get(f"{BASE}/news/?status=draft", **_auth_header(_admin_token()))
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["slug"] == "d1"


@pytest.mark.django_db
def test_list_news_pagination():
    for i in range(5):
        _make_news(slug=f"post-{i}", status="published")
    resp = Client().get(f"{BASE}/news/?page=1&page_size=2")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 5
    assert len(body["items"]) == 2
    assert body["has_next"] is True

    resp2 = Client().get(f"{BASE}/news/?page=3&page_size=2")
    body2 = resp2.json()
    assert len(body2["items"]) == 1
    assert body2["has_next"] is False


@pytest.mark.django_db
def test_list_news_admin_orders_drafts_after_published_not_before():
    """Postgres's SQL-standard default is NULLS FIRST on a DESC sort — a
    naive ``ORDER BY published_at DESC`` would float draft rows
    (``published_at IS NULL``) to the very top of an admin's mixed-status
    listing. The FastAPI original guards against this with
    ``.desc().nullslast()``; assert the Django port orders published items
    first and the draft (null published_at) last."""
    _make_news(slug="draft-post", status="draft")
    _make_news(slug="published-post", status="published")
    resp = Client().get(f"{BASE}/news/", **_auth_header(_admin_token()))
    assert resp.status_code == 200
    slugs = [item["slug"] for item in resp.json()["items"]]
    assert slugs == ["published-post", "draft-post"]


@pytest.mark.django_db
def test_list_news_filter_by_category_slug():
    cat = Category.objects.create(slug="tech", name="Tech")
    _make_news(slug="tech-post", status="published", category_ref=cat)
    _make_news(slug="other-post", status="published")
    resp = Client().get(f"{BASE}/news/?category=tech")
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["slug"] == "tech-post"


@pytest.mark.django_db
def test_list_news_filter_by_tag_slug():
    tag = Tag.objects.create(slug="python", name="Python")
    news = _make_news(slug="py-post", status="published")
    news.tags.set([tag])
    _make_news(slug="other-post", status="published")
    resp = Client().get(f"{BASE}/news/?tag=python")
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["slug"] == "py-post"


@pytest.mark.django_db
def test_list_news_search_q():
    _make_news(slug="hello", title="Hello World", status="published")
    _make_news(slug="bye", title="Goodbye", status="published")
    resp = Client().get(f"{BASE}/news/?q=Hello")
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["slug"] == "hello"


@pytest.mark.django_db
def test_list_news_invalid_status_422():
    resp = Client().get(f"{BASE}/news/?status=bogus")
    assert resp.status_code == 422
    assert "detail" in resp.json()


@pytest.mark.django_db
def test_list_news_page_size_over_max_422():
    resp = Client().get(f"{BASE}/news/?page_size=9999")
    assert resp.status_code == 422


# ── GET /news/by-slug/{slug} ─────────────────────────────────────────────────


@pytest.mark.django_db
def test_get_news_by_slug_public_published():
    _make_news(slug="hello", status="published")
    resp = Client().get(f"{BASE}/news/by-slug/hello")
    assert resp.status_code == 200
    assert resp.json()["slug"] == "hello"


@pytest.mark.django_db
def test_get_news_by_slug_draft_404_for_anonymous():
    _make_news(slug="hello", status="draft")
    resp = Client().get(f"{BASE}/news/by-slug/hello")
    assert resp.status_code == 404
    assert "detail" in resp.json()


@pytest.mark.django_db
def test_get_news_by_slug_draft_visible_to_admin():
    _make_news(slug="hello", status="draft")
    resp = Client().get(f"{BASE}/news/by-slug/hello", **_auth_header(_admin_token()))
    assert resp.status_code == 200


@pytest.mark.django_db
def test_get_news_by_slug_missing_404():
    resp = Client().get(f"{BASE}/news/by-slug/does-not-exist")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_get_news_by_slug_trailing_slash_alias():
    _make_news(slug="hello", status="published")
    resp = Client().get(f"{BASE}/news/by-slug/hello/")
    assert resp.status_code == 200


@pytest.mark.django_db
def test_get_news_by_slug_elapsed_scheduled_visible_to_anonymous():
    """``GET /news/by-slug/{slug}`` shares the LOOSE visibility gate with
    the list route — unlike ``GET /news/{id}``, which is deliberately
    stricter (see ``test_get_news_by_id_elapsed_scheduled_404_for_anonymous``
    below). An elapsed ``scheduled`` item must be visible to anonymous
    callers here, mirroring ``test_list_news_shows_elapsed_scheduled_to_anonymous``."""
    news = _make_news(
        slug="live-now", status="scheduled",
        scheduled_at=timezone.now() - timedelta(minutes=1),
    )
    resp = Client().get(f"{BASE}/news/by-slug/live-now")
    assert resp.status_code == 200
    assert resp.json()["id"] == news.id
    assert resp.json()["slug"] == "live-now"


# ── GET /news/{id} ────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_get_news_by_id_public_published():
    news = _make_news(slug="hello", status="published")
    resp = Client().get(f"{BASE}/news/{news.id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == news.id


@pytest.mark.django_db
def test_get_news_by_id_draft_404_for_anonymous():
    news = _make_news(slug="hello", status="draft")
    resp = Client().get(f"{BASE}/news/{news.id}")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_get_news_by_id_elapsed_scheduled_404_for_anonymous():
    """GET /news/{id} is intentionally stricter than the list/by-slug
    visibility gate in the FastAPI original: only PUBLISHED is visible to
    non-admins here, NOT the elapsed-scheduled lazy-publish case."""
    news = _make_news(
        slug="hello", status="scheduled",
        scheduled_at=timezone.now() - timedelta(minutes=1),
    )
    resp = Client().get(f"{BASE}/news/{news.id}")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_get_news_by_id_missing_404():
    resp = Client().get(f"{BASE}/news/999999")
    assert resp.status_code == 404
    assert "detail" in resp.json()


@pytest.mark.django_db
def test_get_news_by_id_admin_sees_draft():
    news = _make_news(slug="hello", status="draft")
    resp = Client().get(f"{BASE}/news/{news.id}", **_auth_header(_admin_token()))
    assert resp.status_code == 200


@pytest.mark.django_db
def test_get_news_by_id_trailing_slash_alias():
    news = _make_news(slug="hello", status="published")
    resp = Client().get(f"{BASE}/news/{news.id}/")
    assert resp.status_code == 200


# ── POST /news/ ──────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_create_news_without_token_401():
    resp = _post_json(Client(), f"{BASE}/news/", {
        "title": "New", "slug": "new", "status": "draft",
    })
    assert resp.status_code == 401


@pytest.mark.django_db
def test_create_news_non_admin_token_403():
    resp = _post_json(
        Client(), f"{BASE}/news/", {"title": "New", "slug": "new", "status": "draft"},
        **_auth_header(_token()),
    )
    assert resp.status_code == 403


@pytest.mark.django_db
def test_create_news_admin_token_201():
    resp = _post_json(
        Client(), f"{BASE}/news/",
        {"title": "New", "slug": "new", "excerpt": "e", "content": "c", "status": "draft"},
        **_auth_header(_admin_token()),
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["title"] == "New"
    assert body["slug"] == "new"
    assert body["status"] == "draft"
    assert body["published"] is False
    assert body["tags"] == []
    assert body["category"] is None
    assert News.objects.filter(slug="new").exists()


@pytest.mark.django_db
def test_create_news_defaults_author_id_to_admin_when_omitted():
    resp = _post_json(
        Client(), f"{BASE}/news/", {"title": "New", "slug": "new", "status": "draft"},
        **_auth_header(_admin_token()),
    )
    assert resp.status_code == 201
    assert resp.json()["author_id"] == 9


@pytest.mark.django_db
def test_create_news_published_sets_published_true_and_published_at():
    resp = _post_json(
        Client(), f"{BASE}/news/", {"title": "New", "slug": "new", "status": "published"},
        **_auth_header(_admin_token()),
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["published"] is True
    assert body["published_at"] is not None


@pytest.mark.django_db
def test_create_news_with_tags():
    tag = Tag.objects.create(slug="python", name="Python")
    resp = _post_json(
        Client(), f"{BASE}/news/",
        {"title": "New", "slug": "new", "status": "draft", "tag_ids": [tag.id]},
        **_auth_header(_admin_token()),
    )
    assert resp.status_code == 201
    body = resp.json()
    assert [t["slug"] for t in body["tags"]] == ["python"]


@pytest.mark.django_db
def test_create_news_with_category():
    cat = Category.objects.create(slug="tech", name="Tech")
    resp = _post_json(
        Client(), f"{BASE}/news/",
        {"title": "New", "slug": "new", "status": "draft", "category_id": cat.id},
        **_auth_header(_admin_token()),
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["category"]["slug"] == "tech"
    assert body["category_id"] == cat.id


@pytest.mark.django_db
def test_create_news_unknown_tag_id_400():
    resp = _post_json(
        Client(), f"{BASE}/news/",
        {"title": "New", "slug": "new", "status": "draft", "tag_ids": [999999]},
        **_auth_header(_admin_token()),
    )
    assert resp.status_code == 400
    assert "detail" in resp.json()


@pytest.mark.django_db
def test_create_news_invalid_body_422():
    resp = _post_json(
        Client(), f"{BASE}/news/", {"title": "", "slug": "new"},
        **_auth_header(_admin_token()),
    )
    assert resp.status_code == 422
    assert "detail" in resp.json()


@pytest.mark.django_db
def test_create_news_duplicate_slug_409():
    _make_news(slug="dup", status="draft")
    resp = _post_json(
        Client(), f"{BASE}/news/", {"title": "New", "slug": "dup", "status": "draft"},
        **_auth_header(_admin_token()),
    )
    assert resp.status_code == 409
    assert "detail" in resp.json()


@pytest.mark.django_db
def test_create_news_writes_audit_log():
    resp = _post_json(
        Client(), f"{BASE}/news/", {"title": "New", "slug": "new", "status": "draft"},
        **_auth_header(_admin_token()),
    )
    news_id = resp.json()["id"]
    log = AuditLog.objects.get(action="news_created")
    assert log.resource_type == "News"
    assert log.resource_id == str(news_id)
    assert log.user_id == 9


# ── PATCH /news/{id} ─────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_update_news_without_token_401():
    news = _make_news(slug="hello", status="draft")
    resp = _patch_json(Client(), f"{BASE}/news/{news.id}", {"title": "Updated"})
    assert resp.status_code == 401


@pytest.mark.django_db
def test_update_news_non_admin_token_403():
    news = _make_news(slug="hello", status="draft")
    resp = _patch_json(
        Client(), f"{BASE}/news/{news.id}", {"title": "Updated"}, **_auth_header(_token()),
    )
    assert resp.status_code == 403


@pytest.mark.django_db
def test_update_news_admin_token_updates_title():
    news = _make_news(slug="hello", status="draft")
    resp = _patch_json(
        Client(), f"{BASE}/news/{news.id}", {"title": "Updated"},
        **_auth_header(_admin_token()),
    )
    assert resp.status_code == 200
    assert resp.json()["title"] == "Updated"
    news.refresh_from_db()
    assert news.title == "Updated"


@pytest.mark.django_db
def test_update_news_missing_id_404():
    resp = _patch_json(
        Client(), f"{BASE}/news/999999", {"title": "Updated"}, **_auth_header(_admin_token()),
    )
    assert resp.status_code == 404
    assert "detail" in resp.json()


@pytest.mark.django_db
def test_update_news_invalid_body_422():
    news = _make_news(slug="hello", status="draft")
    resp = _patch_json(
        Client(), f"{BASE}/news/{news.id}", {"title": ""}, **_auth_header(_admin_token()),
    )
    assert resp.status_code == 422


@pytest.mark.django_db
def test_update_news_duplicate_slug_409():
    _make_news(slug="taken", status="draft")
    news = _make_news(slug="mine", status="draft")
    resp = _patch_json(
        Client(), f"{BASE}/news/{news.id}", {"slug": "taken"}, **_auth_header(_admin_token()),
    )
    assert resp.status_code == 409


@pytest.mark.django_db
def test_update_news_status_transition_to_published_sets_side_effects():
    news = _make_news(
        slug="hello", status="scheduled", scheduled_at=timezone.now() + timedelta(days=1),
    )
    resp = _patch_json(
        Client(), f"{BASE}/news/{news.id}", {"status": "published"},
        **_auth_header(_admin_token()),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "published"
    assert body["published"] is True
    assert body["published_at"] is not None
    assert body["scheduled_at"] is None
    news.refresh_from_db()
    assert news.published is True
    assert news.scheduled_at is None


@pytest.mark.django_db
def test_update_news_legacy_published_true_maps_to_status_published():
    news = _make_news(slug="hello", status="draft")
    resp = _patch_json(
        Client(), f"{BASE}/news/{news.id}", {"published": True}, **_auth_header(_admin_token()),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "published"
    assert body["published"] is True


@pytest.mark.django_db
def test_update_news_legacy_published_false_maps_to_status_draft():
    news = _make_news(slug="hello", status="published")
    resp = _patch_json(
        Client(), f"{BASE}/news/{news.id}", {"published": False}, **_auth_header(_admin_token()),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "draft"
    assert body["published"] is False


@pytest.mark.django_db
def test_update_news_replaces_tags():
    t1 = Tag.objects.create(slug="a", name="A")
    t2 = Tag.objects.create(slug="b", name="B")
    news = _make_news(slug="hello", status="draft")
    news.tags.set([t1])
    resp = _patch_json(
        Client(), f"{BASE}/news/{news.id}", {"tag_ids": [t2.id]}, **_auth_header(_admin_token()),
    )
    assert resp.status_code == 200
    assert [t["slug"] for t in resp.json()["tags"]] == ["b"]


@pytest.mark.django_db
def test_update_news_unknown_tag_id_400():
    news = _make_news(slug="hello", status="draft")
    resp = _patch_json(
        Client(), f"{BASE}/news/{news.id}", {"tag_ids": [999999]},
        **_auth_header(_admin_token()),
    )
    assert resp.status_code == 400


@pytest.mark.django_db
def test_update_news_trailing_slash_alias():
    news = _make_news(slug="hello", status="draft")
    resp = _patch_json(
        Client(), f"{BASE}/news/{news.id}/", {"title": "Updated"},
        **_auth_header(_admin_token()),
    )
    assert resp.status_code == 200


@pytest.mark.django_db
def test_update_news_writes_audit_log():
    news = _make_news(slug="hello", status="draft")
    resp = _patch_json(
        Client(), f"{BASE}/news/{news.id}", {"title": "Updated"},
        **_auth_header(_admin_token()),
    )
    assert resp.status_code == 200
    log = AuditLog.objects.get(action="news_updated")
    assert log.resource_type == "News"
    assert log.resource_id == str(news.id)
    assert log.user_id == 9
    assert log.changes == {"title": "Updated"}


@pytest.mark.django_db
def test_update_news_scheduled_at_survives_audit_log_as_iso_string():
    """``_json_safe`` (``views.py``) exists specifically so a raw
    ``datetime`` (e.g. ``scheduled_at``) landing in the PATCH audit
    ``changes`` dict doesn't hit ``AuditLog.changes`` — a plain
    ``JSONField`` with no custom encoder — and raise ``TypeError``. No
    other test PATCHes a datetime-bearing field, so without this the fix
    could silently regress and the AuditLog write would start 500ing."""
    news = _make_news(slug="hello", status="draft")
    resp = _patch_json(
        Client(), f"{BASE}/news/{news.id}", {"scheduled_at": "2026-01-01T10:00:00Z"},
        **_auth_header(_admin_token()),
    )
    assert resp.status_code == 200
    log = AuditLog.objects.get(action="news_updated", resource_id=str(news.id))
    assert isinstance(log.changes["scheduled_at"], str)
    assert log.changes["scheduled_at"].startswith("2026-01-01T10:00:00")


@pytest.mark.django_db
def test_update_news_sets_category():
    """``update_news`` translates the incoming ``category_id`` to Django's
    actual FK attribute ``category_ref_id`` (``news_service.py``) — the
    exact bug class that broke serialization on first implementation. Only
    the CREATE path (``test_create_news_with_category``) had a regression
    test; this covers PATCH."""
    cat = Category.objects.create(slug="tech", name="Tech")
    news = _make_news(slug="hello", status="draft")
    resp = _patch_json(
        Client(), f"{BASE}/news/{news.id}", {"category_id": cat.id},
        **_auth_header(_admin_token()),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["category"]["slug"] == "tech"
    assert body["category_id"] == cat.id
    news.refresh_from_db()
    assert news.category_ref_id == cat.id


# ── DELETE /news/{id} ─────────────────────────────────────────────────────


@pytest.mark.django_db
def test_delete_news_without_token_401():
    news = _make_news(slug="hello", status="draft")
    resp = Client().delete(f"{BASE}/news/{news.id}")
    assert resp.status_code == 401


@pytest.mark.django_db
def test_delete_news_non_admin_token_403():
    news = _make_news(slug="hello", status="draft")
    resp = Client().delete(f"{BASE}/news/{news.id}", **_auth_header(_token()))
    assert resp.status_code == 403


@pytest.mark.django_db
def test_delete_news_admin_token_204_empty():
    news = _make_news(slug="hello", status="draft")
    resp = Client().delete(f"{BASE}/news/{news.id}", **_auth_header(_admin_token()))
    assert resp.status_code == 204
    assert resp.content == b""
    assert not News.objects.filter(id=news.id).exists()


@pytest.mark.django_db
def test_delete_news_missing_id_404():
    resp = Client().delete(f"{BASE}/news/999999", **_auth_header(_admin_token()))
    assert resp.status_code == 404
    assert "detail" in resp.json()


@pytest.mark.django_db
def test_delete_news_trailing_slash_alias():
    news = _make_news(slug="hello", status="draft")
    resp = Client().delete(f"{BASE}/news/{news.id}/", **_auth_header(_admin_token()))
    assert resp.status_code == 204


@pytest.mark.django_db
def test_delete_news_writes_audit_log():
    news = _make_news(slug="hello", status="draft")
    resp = Client().delete(f"{BASE}/news/{news.id}", **_auth_header(_admin_token()))
    assert resp.status_code == 204
    log = AuditLog.objects.get(action="news_deleted")
    assert log.resource_type == "News"
    assert log.resource_id == str(news.id)
    assert log.user_id == 9
    assert log.changes == {"slug": "hello"}
