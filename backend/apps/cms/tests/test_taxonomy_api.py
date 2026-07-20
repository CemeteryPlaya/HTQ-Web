"""Contract tests for ``/api/cms/v1/categories/*`` and ``.../tags/*``.

Mirrors ``services/cms/app/api/v1/taxonomy.py``: public list, admin
create/update/delete. Tokens are built with real ``jwt.encode`` against
``settings.JWT_SECRET`` — same style as ``test_contact_requests_api.py``.
"""

import json
import logging

import jwt as pyjwt
import pytest
from django.conf import settings
from django.test import Client

from apps.cms.models import AuditLog, Category, Tag

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


# ── Categories ────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_list_categories_public_no_token():
    Category.objects.create(slug="tech", name="Tech")
    Category.objects.create(slug="hr", name="HR")
    resp = Client().get(f"{BASE}/categories/")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    assert {row["slug"] for row in body} == {"tech", "hr"}


@pytest.mark.django_db
def test_list_categories_empty_ok():
    resp = Client().get(f"{BASE}/categories/")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.django_db
def test_create_category_without_token_401():
    resp = _post_json(Client(), f"{BASE}/categories/", {"slug": "tech", "name": "Tech"})
    assert resp.status_code == 401
    assert "detail" in resp.json()


@pytest.mark.django_db
def test_create_category_non_admin_token_403():
    resp = _post_json(
        Client(), f"{BASE}/categories/", {"slug": "tech", "name": "Tech"},
        **_auth_header(_token()),
    )
    assert resp.status_code == 403


@pytest.mark.django_db
def test_create_category_admin_token_201():
    resp = _post_json(
        Client(), f"{BASE}/categories/", {"slug": "tech", "name": "Tech", "description": "d"},
        **_auth_header(_admin_token()),
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["slug"] == "tech"
    assert body["name"] == "Tech"
    assert body["description"] == "d"
    assert "id" in body and "created_at" in body
    assert Category.objects.filter(slug="tech").exists()


@pytest.mark.django_db
def test_create_category_audit_write_failure_is_non_fatal(monkeypatch, caplog):
    """Consistency fix (R3 review, Finding 4): under autocommit the Category
    row is already committed by the time ``audit.record_action`` runs — an
    audit-insert failure must not 500 an already-successful create. Mirrors
    ``apps.users.tests.test_audit.
    test_admin_create_user_audit_write_failure_is_non_fatal``: force
    ``AuditLog.objects.create`` to raise, do the real mutation over HTTP, and
    assert the endpoint still returns 201, the category still persisted, and
    the failure was logged rather than swallowed silently.
    """

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated audit DB failure")

    monkeypatch.setattr(AuditLog.objects, "create", _boom)

    with caplog.at_level(logging.ERROR, logger="apps.cms.services.audit"):
        resp = _post_json(
            Client(), f"{BASE}/categories/", {"slug": "resilient", "name": "Resilient"},
            **_auth_header(_admin_token()),
        )

    assert resp.status_code == 201
    assert Category.objects.filter(slug="resilient").exists()
    assert not AuditLog.objects.filter(action="category_created").exists()
    assert any(
        "audit record_action failed" in record.getMessage()
        for record in caplog.records
    )


@pytest.mark.django_db
def test_create_category_invalid_body_422():
    resp = _post_json(
        Client(), f"{BASE}/categories/", {"slug": "Not Valid Slug!", "name": "Tech"},
        **_auth_header(_admin_token()),
    )
    assert resp.status_code == 422
    assert "detail" in resp.json()


@pytest.mark.django_db
def test_create_category_duplicate_slug_409():
    Category.objects.create(slug="tech", name="Tech")
    resp = _post_json(
        Client(), f"{BASE}/categories/", {"slug": "tech", "name": "Tech 2"},
        **_auth_header(_admin_token()),
    )
    assert resp.status_code == 409
    assert "detail" in resp.json()


@pytest.mark.django_db
def test_update_category_without_token_401():
    cat = Category.objects.create(slug="tech", name="Tech")
    resp = _patch_json(Client(), f"{BASE}/categories/{cat.id}", {"name": "New"})
    assert resp.status_code == 401


@pytest.mark.django_db
def test_update_category_non_admin_token_403():
    cat = Category.objects.create(slug="tech", name="Tech")
    resp = _patch_json(
        Client(), f"{BASE}/categories/{cat.id}", {"name": "New"}, **_auth_header(_token()),
    )
    assert resp.status_code == 403


@pytest.mark.django_db
def test_update_category_admin_token_updates():
    cat = Category.objects.create(slug="tech", name="Tech")
    resp = _patch_json(
        Client(), f"{BASE}/categories/{cat.id}", {"name": "Technology"},
        **_auth_header(_admin_token()),
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Technology"
    cat.refresh_from_db()
    assert cat.name == "Technology"


@pytest.mark.django_db
def test_update_category_trailing_slash_alias():
    cat = Category.objects.create(slug="tech", name="Tech")
    resp = _patch_json(
        Client(), f"{BASE}/categories/{cat.id}/", {"name": "Technology"},
        **_auth_header(_admin_token()),
    )
    assert resp.status_code == 200


@pytest.mark.django_db
def test_update_category_missing_id_404():
    resp = _patch_json(
        Client(), f"{BASE}/categories/999999", {"name": "X"}, **_auth_header(_admin_token()),
    )
    assert resp.status_code == 404
    assert "detail" in resp.json()


@pytest.mark.django_db
def test_delete_category_without_token_401():
    cat = Category.objects.create(slug="tech", name="Tech")
    resp = Client().delete(f"{BASE}/categories/{cat.id}")
    assert resp.status_code == 401


@pytest.mark.django_db
def test_delete_category_non_admin_token_403():
    cat = Category.objects.create(slug="tech", name="Tech")
    resp = Client().delete(f"{BASE}/categories/{cat.id}", **_auth_header(_token()))
    assert resp.status_code == 403


@pytest.mark.django_db
def test_delete_category_admin_token_204_empty():
    cat = Category.objects.create(slug="tech", name="Tech")
    resp = Client().delete(f"{BASE}/categories/{cat.id}", **_auth_header(_admin_token()))
    assert resp.status_code == 204
    assert resp.content == b""
    assert not Category.objects.filter(id=cat.id).exists()


@pytest.mark.django_db
def test_delete_category_trailing_slash_alias():
    cat = Category.objects.create(slug="tech", name="Tech")
    resp = Client().delete(f"{BASE}/categories/{cat.id}/", **_auth_header(_admin_token()))
    assert resp.status_code == 204


@pytest.mark.django_db
def test_delete_category_missing_id_404():
    resp = Client().delete(f"{BASE}/categories/999999", **_auth_header(_admin_token()))
    assert resp.status_code == 404


@pytest.mark.django_db
def test_category_writes_audit_log():
    resp = _post_json(
        Client(), f"{BASE}/categories/", {"slug": "tech", "name": "Tech"},
        **_auth_header(_admin_token()),
    )
    cat_id = resp.json()["id"]
    log = AuditLog.objects.get(action="category_created")
    assert log.resource_type == "Category"
    assert log.resource_id == str(cat_id)
    assert log.user_id == 9


# ── Tags ──────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_list_tags_public_no_token():
    Tag.objects.create(slug="python", name="Python")
    Tag.objects.create(slug="react", name="React")
    resp = Client().get(f"{BASE}/tags/")
    assert resp.status_code == 200
    body = resp.json()
    assert {row["slug"] for row in body} == {"python", "react"}


@pytest.mark.django_db
def test_create_tag_without_token_401():
    resp = _post_json(Client(), f"{BASE}/tags/", {"slug": "python", "name": "Python"})
    assert resp.status_code == 401


@pytest.mark.django_db
def test_create_tag_non_admin_token_403():
    resp = _post_json(
        Client(), f"{BASE}/tags/", {"slug": "python", "name": "Python"},
        **_auth_header(_token()),
    )
    assert resp.status_code == 403


@pytest.mark.django_db
def test_create_tag_admin_token_201():
    resp = _post_json(
        Client(), f"{BASE}/tags/", {"slug": "python", "name": "Python"},
        **_auth_header(_admin_token()),
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["slug"] == "python"
    assert body["name"] == "Python"
    assert Tag.objects.filter(slug="python").exists()


@pytest.mark.django_db
def test_create_tag_invalid_body_422():
    resp = _post_json(
        Client(), f"{BASE}/tags/", {"slug": "Not Valid!", "name": "Python"},
        **_auth_header(_admin_token()),
    )
    assert resp.status_code == 422


@pytest.mark.django_db
def test_create_tag_duplicate_slug_409():
    Tag.objects.create(slug="python", name="Python")
    resp = _post_json(
        Client(), f"{BASE}/tags/", {"slug": "python", "name": "Python 2"},
        **_auth_header(_admin_token()),
    )
    assert resp.status_code == 409


@pytest.mark.django_db
def test_update_tag_without_token_401():
    tag = Tag.objects.create(slug="python", name="Python")
    resp = _patch_json(Client(), f"{BASE}/tags/{tag.id}", {"name": "New"})
    assert resp.status_code == 401


@pytest.mark.django_db
def test_update_tag_non_admin_token_403():
    tag = Tag.objects.create(slug="python", name="Python")
    resp = _patch_json(
        Client(), f"{BASE}/tags/{tag.id}", {"name": "New"}, **_auth_header(_token()),
    )
    assert resp.status_code == 403


@pytest.mark.django_db
def test_update_tag_admin_token_updates():
    tag = Tag.objects.create(slug="python", name="Python")
    resp = _patch_json(
        Client(), f"{BASE}/tags/{tag.id}", {"name": "Python3"}, **_auth_header(_admin_token()),
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Python3"


@pytest.mark.django_db
def test_update_tag_missing_id_404():
    resp = _patch_json(
        Client(), f"{BASE}/tags/999999", {"name": "X"}, **_auth_header(_admin_token()),
    )
    assert resp.status_code == 404


@pytest.mark.django_db
def test_delete_tag_without_token_401():
    tag = Tag.objects.create(slug="python", name="Python")
    resp = Client().delete(f"{BASE}/tags/{tag.id}")
    assert resp.status_code == 401


@pytest.mark.django_db
def test_delete_tag_non_admin_token_403():
    tag = Tag.objects.create(slug="python", name="Python")
    resp = Client().delete(f"{BASE}/tags/{tag.id}", **_auth_header(_token()))
    assert resp.status_code == 403


@pytest.mark.django_db
def test_delete_tag_admin_token_204_empty():
    tag = Tag.objects.create(slug="python", name="Python")
    resp = Client().delete(f"{BASE}/tags/{tag.id}", **_auth_header(_admin_token()))
    assert resp.status_code == 204
    assert resp.content == b""
    assert not Tag.objects.filter(id=tag.id).exists()


@pytest.mark.django_db
def test_delete_tag_missing_id_404():
    resp = Client().delete(f"{BASE}/tags/999999", **_auth_header(_admin_token()))
    assert resp.status_code == 404
