"""Contract tests for ``/api/users/v1/items/*`` (Task 2.5).

Mirrors ``services/user/app/api/v1/items.py`` (the FastAPI original):
strictly owner-scoped CRUD. A non-owner (or unauthenticated caller)
addressing another user's item id gets 404 — the source's WHERE clause
makes "not yours" indistinguishable from "doesn't exist", reproduced the
same way (see ``apps.users.services.items_service`` module docstring).
"""

import pytest
from django.test import Client

from apps.users.models import Item, User, UserStatus
from htqweb.authn.jwt import issue_token_pair

BASE = "/api/users/v1"


@pytest.fixture
def alice(db):
    u = User.objects.create(username="alice", email="alice@htq.test", password="x",
                            status=UserStatus.ACTIVE, first_name="Alice", last_name="Smith")
    u.set_password("S3cret!")
    u.save()
    return u


@pytest.fixture
def bob(db):
    u = User.objects.create(username="bob", email="bob@htq.test", password="x",
                            status=UserStatus.ACTIVE, first_name="Bob", last_name="Jones")
    u.set_password("S3cret!")
    u.save()
    return u


def _auth(user) -> dict:
    token = issue_token_pair(user)["access"]
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


ITEM_FIELDS = {"id", "title", "description", "owner_id", "created_at"}


# ── GET items/ ────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_list_items_401_without_token(db):
    resp = Client().get(f"{BASE}/items/")
    assert resp.status_code == 401


@pytest.mark.django_db
def test_list_items_empty(alice):
    resp = Client().get(f"{BASE}/items/", **_auth(alice))
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.django_db
def test_list_items_only_own(alice, bob):
    Item.objects.create(title="Alice item", owner=alice)
    Item.objects.create(title="Bob item", owner=bob)

    resp = Client().get(f"{BASE}/items/", **_auth(alice))
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["title"] == "Alice item"
    assert body[0]["owner_id"] == alice.id
    assert set(body[0]) == ITEM_FIELDS
    # Bob's item must not leak into Alice's list.
    assert all(row["title"] != "Bob item" for row in body)


# ── POST items/ ───────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_create_item_401_without_token(db):
    resp = Client().post(f"{BASE}/items/", data={"title": "x"}, content_type="application/json")
    assert resp.status_code == 401


@pytest.mark.django_db
def test_create_item_201_owned_by_caller(alice):
    resp = Client().post(f"{BASE}/items/", data={
        "title": "My note", "description": "details",
    }, content_type="application/json", **_auth(alice))
    assert resp.status_code == 201
    body = resp.json()
    assert set(body) == ITEM_FIELDS
    assert body["title"] == "My note"
    assert body["description"] == "details"
    assert body["owner_id"] == alice.id

    item = Item.objects.get(id=body["id"])
    assert item.owner_id == alice.id


@pytest.mark.django_db
def test_create_item_default_description(alice):
    resp = Client().post(f"{BASE}/items/", data={"title": "No desc"},
                         content_type="application/json", **_auth(alice))
    assert resp.status_code == 201
    assert resp.json()["description"] == ""


@pytest.mark.django_db
def test_create_item_422_missing_title(alice):
    resp = Client().post(f"{BASE}/items/", data={}, content_type="application/json",
                         **_auth(alice))
    assert resp.status_code == 422


# ── GET items/{id}/ ───────────────────────────────────────────────────────


@pytest.mark.django_db
def test_get_item_401_without_token(alice):
    item = Item.objects.create(title="x", owner=alice)
    resp = Client().get(f"{BASE}/items/{item.id}/")
    assert resp.status_code == 401


@pytest.mark.django_db
def test_get_item_200_own(alice):
    item = Item.objects.create(title="Mine", description="d", owner=alice)
    resp = Client().get(f"{BASE}/items/{item.id}/", **_auth(alice))
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == item.id
    assert body["title"] == "Mine"


@pytest.mark.django_db
def test_get_item_404_nonexistent(alice):
    resp = Client().get(f"{BASE}/items/999999/", **_auth(alice))
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Item not found"}


@pytest.mark.django_db
def test_get_item_404_not_owner(alice, bob):
    """Accessing another user's item 404s (not 403) — matches the source's
    owner-scoped WHERE clause."""
    item = Item.objects.create(title="Bob's", owner=bob)
    resp = Client().get(f"{BASE}/items/{item.id}/", **_auth(alice))
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Item not found"}


# ── PATCH items/{id}/ ─────────────────────────────────────────────────────


@pytest.mark.django_db
def test_patch_item_401_without_token(alice):
    item = Item.objects.create(title="x", owner=alice)
    resp = Client().patch(f"{BASE}/items/{item.id}/", data={"title": "y"},
                          content_type="application/json")
    assert resp.status_code == 401


@pytest.mark.django_db
def test_patch_item_200_own(alice):
    item = Item.objects.create(title="Old", description="old-d", owner=alice)
    resp = Client().patch(f"{BASE}/items/{item.id}/", data={"title": "New"},
                          content_type="application/json", **_auth(alice))
    assert resp.status_code == 200
    body = resp.json()
    assert body["title"] == "New"
    assert body["description"] == "old-d"  # unset field untouched

    item.refresh_from_db()
    assert item.title == "New"
    assert item.description == "old-d"


@pytest.mark.django_db
def test_patch_item_404_not_owner(alice, bob):
    item = Item.objects.create(title="Bob's", owner=bob)
    resp = Client().patch(f"{BASE}/items/{item.id}/", data={"title": "hijacked"},
                          content_type="application/json", **_auth(alice))
    assert resp.status_code == 404
    item.refresh_from_db()
    assert item.title == "Bob's"


@pytest.mark.django_db
def test_patch_item_404_nonexistent(alice):
    resp = Client().patch(f"{BASE}/items/999999/", data={"title": "y"},
                          content_type="application/json", **_auth(alice))
    assert resp.status_code == 404


# ── DELETE items/{id}/ ────────────────────────────────────────────────────


@pytest.mark.django_db
def test_delete_item_401_without_token(alice):
    item = Item.objects.create(title="x", owner=alice)
    resp = Client().delete(f"{BASE}/items/{item.id}/")
    assert resp.status_code == 401


@pytest.mark.django_db
def test_delete_item_204_own(alice):
    item = Item.objects.create(title="x", owner=alice)
    resp = Client().delete(f"{BASE}/items/{item.id}/", **_auth(alice))
    assert resp.status_code == 204
    assert resp.content == b""
    assert not Item.objects.filter(id=item.id).exists()


@pytest.mark.django_db
def test_delete_item_404_not_owner(alice, bob):
    item = Item.objects.create(title="Bob's", owner=bob)
    resp = Client().delete(f"{BASE}/items/{item.id}/", **_auth(alice))
    assert resp.status_code == 404
    assert Item.objects.filter(id=item.id).exists()  # not deleted


@pytest.mark.django_db
def test_delete_item_404_nonexistent(alice):
    resp = Client().delete(f"{BASE}/items/999999/", **_auth(alice))
    assert resp.status_code == 404


# ── GET items/{id}/ — method not allowed on collection with a bad verb ─────


@pytest.mark.django_db
def test_items_collection_405_unsupported_method(alice):
    resp = Client().delete(f"{BASE}/items/", **_auth(alice))
    assert resp.status_code == 405
