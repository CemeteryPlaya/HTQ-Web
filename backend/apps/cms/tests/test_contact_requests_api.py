"""Contract tests for ``/api/cms/v1/contact-requests/*``.

Mirrors ``services/cms/app/api/v1/contact_requests.py``: public POST, admin
list/stats/detail/patch/reply/delete. Tokens are built with real
``jwt.encode`` against ``settings.JWT_SECRET`` (no mocking of
``decode_token``) — same style as ``apps/core/tests/test_api_view.py``.
"""

import json

import jwt as pyjwt
import pytest
from django.conf import settings
from django.test import Client

from apps.cms.models import ContactRequest

BASE = "/api/cms/v1/contact-requests"


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


# ── POST / — public ──────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_public_post_without_token_succeeds_and_persists():
    client = Client()
    resp = _post_json(client, f"{BASE}/", {
        "first_name": "Alice", "last_name": "Doe", "email": "alice@example.com", "message": "hi",
    })
    assert resp.status_code == 201
    body = resp.json()
    assert body["email"] == "alice@example.com"
    assert body["first_name"] == "Alice"
    assert body["handled"] is False
    assert body["reply_message"] == ""
    entry = ContactRequest.objects.get(email="alice@example.com")
    assert entry.message == "hi"


@pytest.mark.django_db
def test_public_post_invalid_body_422_with_detail():
    client = Client()
    resp = _post_json(client, f"{BASE}/", {"email": "not-an-email"})
    assert resp.status_code == 422
    assert "detail" in resp.json()
    assert not ContactRequest.objects.exists()


# ── admin routes: no token -> 401 ────────────────────────────────────────────

@pytest.mark.django_db
def test_list_without_token_401():
    resp = Client().get(f"{BASE}/")
    assert resp.status_code == 401
    assert "detail" in resp.json()


@pytest.mark.django_db
def test_stats_without_token_401():
    resp = Client().get(f"{BASE}/stats")
    assert resp.status_code == 401
    assert "detail" in resp.json()


@pytest.mark.django_db
def test_stats_slash_alias_without_token_401():
    resp = Client().get(f"{BASE}/stats/")
    assert resp.status_code == 401
    assert "detail" in resp.json()


@pytest.mark.django_db
def test_detail_without_token_401():
    entry = ContactRequest.objects.create(email="x@x.com")
    resp = Client().get(f"{BASE}/{entry.id}")
    assert resp.status_code == 401


@pytest.mark.django_db
def test_patch_without_token_401():
    entry = ContactRequest.objects.create(email="x@x.com")
    resp = _patch_json(Client(), f"{BASE}/{entry.id}", {"handled": True})
    assert resp.status_code == 401


@pytest.mark.django_db
def test_reply_without_token_401():
    entry = ContactRequest.objects.create(email="x@x.com")
    resp = _post_json(Client(), f"{BASE}/{entry.id}/reply", {"reply_message": "hello"})
    assert resp.status_code == 401


@pytest.mark.django_db
def test_delete_without_token_401():
    entry = ContactRequest.objects.create(email="x@x.com")
    resp = Client().delete(f"{BASE}/{entry.id}")
    assert resp.status_code == 401


# ── admin routes: valid non-admin token -> 403 ───────────────────────────────

@pytest.mark.django_db
def test_list_non_admin_token_403():
    resp = Client().get(f"{BASE}/", **_auth_header(_token()))
    assert resp.status_code == 403
    assert "detail" in resp.json()


@pytest.mark.django_db
def test_stats_non_admin_token_403():
    resp = Client().get(f"{BASE}/stats", **_auth_header(_token()))
    assert resp.status_code == 403


@pytest.mark.django_db
def test_detail_non_admin_token_403():
    entry = ContactRequest.objects.create(email="x@x.com")
    resp = Client().get(f"{BASE}/{entry.id}", **_auth_header(_token()))
    assert resp.status_code == 403


@pytest.mark.django_db
def test_patch_non_admin_token_403():
    entry = ContactRequest.objects.create(email="x@x.com")
    resp = _patch_json(Client(), f"{BASE}/{entry.id}", {"handled": True}, **_auth_header(_token()))
    assert resp.status_code == 403


@pytest.mark.django_db
def test_reply_non_admin_token_403():
    entry = ContactRequest.objects.create(email="x@x.com")
    resp = _post_json(Client(), f"{BASE}/{entry.id}/reply", {"reply_message": "hi"}, **_auth_header(_token()))
    assert resp.status_code == 403


@pytest.mark.django_db
def test_delete_non_admin_token_403():
    entry = ContactRequest.objects.create(email="x@x.com")
    resp = Client().delete(f"{BASE}/{entry.id}", **_auth_header(_token()))
    assert resp.status_code == 403


# ── admin routes: admin token -> success ─────────────────────────────────────

@pytest.mark.django_db
def test_list_admin_token_returns_rows():
    ContactRequest.objects.create(email="a@a.com")
    ContactRequest.objects.create(email="b@b.com")
    resp = Client().get(f"{BASE}/", **_auth_header(_admin_token()))
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    assert {row["email"] for row in body} == {"a@a.com", "b@b.com"}


@pytest.mark.django_db
def test_list_admin_token_filters_by_handled():
    ContactRequest.objects.create(email="unhandled@x.com", handled=False)
    ContactRequest.objects.create(email="handled@x.com", handled=True)
    resp = Client().get(f"{BASE}/?handled=true", **_auth_header(_admin_token()))
    assert resp.status_code == 200
    body = resp.json()
    assert [row["email"] for row in body] == ["handled@x.com"]


@pytest.mark.django_db
def test_stats_admin_token_reports_unhandled_count():
    ContactRequest.objects.create(email="a@a.com", handled=False)
    ContactRequest.objects.create(email="b@b.com", handled=True)
    resp = Client().get(f"{BASE}/stats", **_auth_header(_admin_token()))
    assert resp.status_code == 200
    assert resp.json() == {"unhandled": 1}


@pytest.mark.django_db
def test_stats_slash_alias_admin_token_same_as_bare():
    ContactRequest.objects.create(email="a@a.com", handled=False)
    resp = Client().get(f"{BASE}/stats/", **_auth_header(_admin_token()))
    assert resp.status_code == 200
    assert resp.json() == {"unhandled": 1}


@pytest.mark.django_db
def test_detail_admin_token_returns_entry():
    entry = ContactRequest.objects.create(email="x@x.com", first_name="X")
    resp = Client().get(f"{BASE}/{entry.id}", **_auth_header(_admin_token()))
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == entry.id
    assert body["email"] == "x@x.com"


@pytest.mark.django_db
def test_patch_admin_token_updates_entry():
    entry = ContactRequest.objects.create(email="x@x.com")
    resp = _patch_json(Client(), f"{BASE}/{entry.id}", {"handled": True}, **_auth_header(_admin_token()))
    assert resp.status_code == 200
    assert resp.json()["handled"] is True
    entry.refresh_from_db()
    assert entry.handled is True


@pytest.mark.django_db
def test_reply_admin_token_sets_reply_fields_and_marks_handled():
    entry = ContactRequest.objects.create(email="x@x.com")
    resp = _post_json(
        Client(), f"{BASE}/{entry.id}/reply", {"reply_message": "we got it"},
        **_auth_header(_admin_token()),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["reply_message"] == "we got it"
    assert body["handled"] is True
    assert body["replied_by_id"] == 9
    assert body["replied_at"] is not None
    entry.refresh_from_db()
    assert entry.reply_message == "we got it"
    assert entry.handled is True
    assert entry.replied_by_id == 9


@pytest.mark.django_db
def test_delete_admin_token_204_empty_body_and_row_gone():
    entry = ContactRequest.objects.create(email="x@x.com")
    resp = Client().delete(f"{BASE}/{entry.id}", **_auth_header(_admin_token()))
    assert resp.status_code == 204
    assert resp.content == b""
    assert not ContactRequest.objects.filter(id=entry.id).exists()


# ── not found ─────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_get_nonexistent_id_404_with_detail():
    resp = Client().get(f"{BASE}/999999", **_auth_header(_admin_token()))
    assert resp.status_code == 404
    assert "detail" in resp.json()
