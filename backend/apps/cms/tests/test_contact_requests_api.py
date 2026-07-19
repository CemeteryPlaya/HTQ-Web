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

from apps.cms.models import AuditLog, ContactRequest

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
def test_public_post_succeeds_even_if_notification_enqueue_raises(monkeypatch):
    """Review finding on Task 1.7: async_task(...) at the create call site
    was unguarded. In Q_CLUSTER["sync"]=True (this whole suite) django-q2's
    executor re-raises the task's own exception back to the caller of
    async_task — so a notification/broker hiccup would 500 the submitter
    even though the ContactRequest row + audit entry were already committed.
    Force that path by making the enqueue call itself raise, and assert the
    public POST still returns 201 with the persisted row intact."""
    def _boom(*args, **kwargs):
        raise RuntimeError("broker unreachable")

    monkeypatch.setattr("apps.cms.views.async_task", _boom)

    client = Client()
    before = ContactRequest.objects.count()
    resp = _post_json(client, f"{BASE}/", {
        "first_name": "Bob", "last_name": "Roe", "email": "bob@example.com", "message": "hi",
    })
    assert resp.status_code == 201
    body = resp.json()
    assert body["email"] == "bob@example.com"
    assert ContactRequest.objects.count() == before + 1
    assert ContactRequest.objects.filter(email="bob@example.com").exists()


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


@pytest.mark.django_db
def test_get_nonexistent_id_404_detail_is_specific_message():
    """Finding 4: htqweb.http.api_view must forward Http404's own message
    (get_contact_request_or_404 raises Http404("Contact request not found"))
    instead of collapsing it to the generic "Not Found"."""
    resp = Client().get(f"{BASE}/999999", **_auth_header(_admin_token()))
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Contact request not found"}


# ── trailing-slash aliases on /{id} and /{id}/reply ──────────────────────────
#
# Finding 1: the real frontend (AdminContacts.tsx) calls
# `contact-requests/{id}/` (PATCH, DELETE) WITH a trailing slash, but the
# route was only ever registered without one. APPEND_SLASH=False means
# Django never redirects, so that spelling 404s outright — these tests hit
# exactly the spelling the frontend sends, not just the spelling the
# implementation happened to use.

@pytest.mark.django_db
def test_patch_trailing_slash_matches_frontend_call_site():
    entry = ContactRequest.objects.create(email="x@x.com")
    resp = _patch_json(Client(), f"{BASE}/{entry.id}/", {"handled": True}, **_auth_header(_admin_token()))
    assert resp.status_code == 200
    assert resp.json()["handled"] is True
    entry.refresh_from_db()
    assert entry.handled is True


@pytest.mark.django_db
def test_delete_trailing_slash_matches_frontend_call_site():
    entry = ContactRequest.objects.create(email="x@x.com")
    resp = Client().delete(f"{BASE}/{entry.id}/", **_auth_header(_admin_token()))
    assert resp.status_code == 204
    assert not ContactRequest.objects.filter(id=entry.id).exists()


@pytest.mark.django_db
def test_get_detail_trailing_slash_alias():
    entry = ContactRequest.objects.create(email="x@x.com")
    resp = Client().get(f"{BASE}/{entry.id}/", **_auth_header(_admin_token()))
    assert resp.status_code == 200
    assert resp.json()["id"] == entry.id


@pytest.mark.django_db
def test_reply_trailing_slash_alias():
    entry = ContactRequest.objects.create(email="x@x.com")
    resp = _post_json(
        Client(), f"{BASE}/{entry.id}/reply/", {"reply_message": "we got it"},
        **_auth_header(_admin_token()),
    )
    assert resp.status_code == 200
    assert resp.json()["reply_message"] == "we got it"


# ── query param validation (Finding 2) ───────────────────────────────────────

@pytest.mark.django_db
def test_list_limit_zero_422():
    resp = Client().get(f"{BASE}/?limit=0", **_auth_header(_admin_token()))
    assert resp.status_code == 422
    assert "detail" in resp.json()


@pytest.mark.django_db
def test_list_limit_over_max_422():
    resp = Client().get(f"{BASE}/?limit=9999", **_auth_header(_admin_token()))
    assert resp.status_code == 422
    assert "detail" in resp.json()


@pytest.mark.django_db
def test_list_limit_non_numeric_422():
    resp = Client().get(f"{BASE}/?limit=abc", **_auth_header(_admin_token()))
    assert resp.status_code == 422
    assert "detail" in resp.json()


@pytest.mark.django_db
def test_list_handled_invalid_value_422():
    resp = Client().get(f"{BASE}/?handled=maybe", **_auth_header(_admin_token()))
    assert resp.status_code == 422
    assert "detail" in resp.json()


@pytest.mark.django_db
def test_list_valid_limit_and_offset_still_works():
    for i in range(3):
        ContactRequest.objects.create(email=f"{i}@x.com")
    resp = Client().get(f"{BASE}/?limit=500&offset=0", **_auth_header(_admin_token()))
    assert resp.status_code == 200
    assert len(resp.json()) == 3


# ── audit trail (Finding 3) ───────────────────────────────────────────────────

@pytest.mark.django_db
def test_public_post_writes_audit_log():
    client = Client()
    resp = _post_json(client, f"{BASE}/", {
        "first_name": "Alice", "last_name": "Doe", "email": "alice@example.com", "message": "hi",
    })
    assert resp.status_code == 201
    entry_id = resp.json()["id"]
    log = AuditLog.objects.get(action="contact_request_submitted")
    assert log.resource_type == "ContactRequest"
    assert log.resource_id == str(entry_id)
    assert log.user_id is None
    assert log.changes == {"email": "alice@example.com"}


@pytest.mark.django_db
def test_patch_writes_audit_log_with_actor_and_changes():
    entry = ContactRequest.objects.create(email="x@x.com")
    resp = _patch_json(Client(), f"{BASE}/{entry.id}", {"handled": True}, **_auth_header(_admin_token()))
    assert resp.status_code == 200
    log = AuditLog.objects.get(action="contact_request_updated")
    assert log.resource_type == "ContactRequest"
    assert log.resource_id == str(entry.id)
    assert log.user_id == 9
    assert log.changes == {"handled": True}


@pytest.mark.django_db
def test_reply_writes_audit_log_with_actor_and_reply_message():
    entry = ContactRequest.objects.create(email="x@x.com")
    resp = _post_json(
        Client(), f"{BASE}/{entry.id}/reply", {"reply_message": "we got it"},
        **_auth_header(_admin_token()),
    )
    assert resp.status_code == 200
    log = AuditLog.objects.get(action="contact_request_replied")
    assert log.resource_type == "ContactRequest"
    assert log.resource_id == str(entry.id)
    assert log.user_id == 9
    assert log.changes == {"reply_message": "we got it"}


@pytest.mark.django_db
def test_delete_writes_audit_log_with_actor_and_email():
    entry = ContactRequest.objects.create(email="x@x.com")
    resp = Client().delete(f"{BASE}/{entry.id}", **_auth_header(_admin_token()))
    assert resp.status_code == 204
    log = AuditLog.objects.get(action="contact_request_deleted")
    assert log.resource_type == "ContactRequest"
    assert log.resource_id == str(entry.id)
    assert log.user_id == 9
    assert log.changes == {"email": "x@x.com"}
