"""Contract tests for ``/api/users/v1/client-errors(/)`` and
``client-events(/)`` (Task 2.5).

Mirrors ``services/user/app/api/v1/client_errors.py`` (the FastAPI
original): both endpoints are log-only sinks — nothing is ever persisted to
SQL — and accept anonymous callers (optional JWT, ``auto_error=False`` in
the source) so pre-login crashes and logouts are captured. A missing or
even garbage Authorization header must never 401; both always return 202.
"""

import logging

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


def _auth(user) -> dict:
    token = issue_token_pair(user)["access"]
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


ERROR_PAYLOAD = {"message": "boom", "url": "https://app.htq.test/page", "stack": "Error: boom\n  at x"}
EVENT_PAYLOAD = {"action": "login_success", "url": "https://app.htq.test/login"}


# ── client-errors ─────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_client_errors_202_anonymous(db):
    resp = Client().post(f"{BASE}/client-errors", data=ERROR_PAYLOAD, content_type="application/json")
    assert resp.status_code == 202
    assert resp.json() == {"ok": True}


@pytest.mark.django_db
def test_client_errors_slash_alias_202(db):
    resp = Client().post(f"{BASE}/client-errors/", data=ERROR_PAYLOAD, content_type="application/json")
    assert resp.status_code == 202


@pytest.mark.django_db
def test_client_errors_202_with_valid_token(alice):
    resp = Client().post(f"{BASE}/client-errors", data=ERROR_PAYLOAD, content_type="application/json",
                         **_auth(alice))
    assert resp.status_code == 202


@pytest.mark.django_db
def test_client_errors_202_with_garbage_authorization_header(db):
    """A malformed/garbage bearer token must never 401 here — the endpoint
    stays anonymous-but-accepted, never rejected."""
    resp = Client().post(f"{BASE}/client-errors", data=ERROR_PAYLOAD, content_type="application/json",
                         HTTP_AUTHORIZATION="Bearer not-a-real-jwt-at-all")
    assert resp.status_code == 202
    assert resp.json() == {"ok": True}


@pytest.mark.django_db
def test_client_errors_202_with_missing_bearer_scheme(db):
    resp = Client().post(f"{BASE}/client-errors", data=ERROR_PAYLOAD, content_type="application/json",
                         HTTP_AUTHORIZATION="totally-invalid")
    assert resp.status_code == 202


@pytest.mark.django_db
def test_client_errors_422_missing_required_field(db):
    """``message``/``url`` are required — an omitted field 422s (matches the
    FastAPI original's Pydantic model validation), it does not silently 202."""
    resp = Client().post(f"{BASE}/client-errors", data={"message": "boom"},
                         content_type="application/json")
    assert resp.status_code == 422


@pytest.mark.django_db
def test_client_errors_405_wrong_method(db):
    resp = Client().get(f"{BASE}/client-errors")
    assert resp.status_code == 405


@pytest.mark.django_db
def test_client_errors_enriches_log_with_user_id(alice, caplog):
    with caplog.at_level(logging.ERROR, logger="apps.users.views"):
        resp = Client().post(f"{BASE}/client-errors", data=ERROR_PAYLOAD, content_type="application/json",
                             **_auth(alice))
    assert resp.status_code == 202
    assert any(f"user_id={alice.id}" in rec.getMessage() for rec in caplog.records)


@pytest.mark.django_db
def test_client_errors_refresh_token_not_attributed(alice, caplog):
    """R6 Fix 1: ``_maybe_user_id`` must check ``token_type`` — a refresh
    token in the Authorization header must not be attributed as the caller,
    only an access token may enrich the log with ``user_id``."""
    refresh_token = issue_token_pair(alice)["refresh"]
    with caplog.at_level(logging.ERROR, logger="apps.users.views"):
        resp = Client().post(
            f"{BASE}/client-errors", data=ERROR_PAYLOAD, content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {refresh_token}",
        )
    assert resp.status_code == 202
    assert any("user_id=None" in rec.getMessage() for rec in caplog.records)
    assert not any(f"user_id={alice.id}" in rec.getMessage() for rec in caplog.records)


# ── client-events ─────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_client_events_202_anonymous(db):
    resp = Client().post(f"{BASE}/client-events", data=EVENT_PAYLOAD, content_type="application/json")
    assert resp.status_code == 202
    assert resp.json() == {"ok": True}


@pytest.mark.django_db
def test_client_events_slash_alias_202(db):
    resp = Client().post(f"{BASE}/client-events/", data=EVENT_PAYLOAD, content_type="application/json")
    assert resp.status_code == 202


@pytest.mark.django_db
def test_client_events_202_with_valid_token(alice):
    resp = Client().post(f"{BASE}/client-events", data=EVENT_PAYLOAD, content_type="application/json",
                         **_auth(alice))
    assert resp.status_code == 202


@pytest.mark.django_db
def test_client_events_202_with_garbage_authorization_header(db):
    resp = Client().post(f"{BASE}/client-events", data=EVENT_PAYLOAD, content_type="application/json",
                         HTTP_AUTHORIZATION="Bearer garbage.garbage.garbage")
    assert resp.status_code == 202


@pytest.mark.django_db
def test_client_events_422_missing_required_field(db):
    resp = Client().post(f"{BASE}/client-events", data={"url": "https://x"},
                         content_type="application/json")
    assert resp.status_code == 422


@pytest.mark.django_db
def test_client_events_with_resource_fields(alice):
    resp = Client().post(f"{BASE}/client-events", data={
        **EVENT_PAYLOAD, "resource": "Item", "resourceId": 42, "meta": {"foo": "bar"},
    }, content_type="application/json", **_auth(alice))
    assert resp.status_code == 202


# ── nothing is ever persisted to SQL ──────────────────────────────────────


@pytest.mark.django_db
def test_telemetry_persists_nothing(alice):
    """Both endpoints are log-only sinks — no model, no table. Fire a batch
    of requests (anonymous + authenticated + malformed-body-adjacent
    optional fields) and assert user/item row counts are unchanged."""
    user_count_before = User.objects.count()
    item_count_before = Item.objects.count()

    client = Client()
    client.post(f"{BASE}/client-errors", data=ERROR_PAYLOAD, content_type="application/json")
    client.post(f"{BASE}/client-errors/", data=ERROR_PAYLOAD, content_type="application/json", **_auth(alice))
    client.post(f"{BASE}/client-events", data=EVENT_PAYLOAD, content_type="application/json")
    client.post(f"{BASE}/client-events/", data={
        **EVENT_PAYLOAD, "resource": "Item", "resourceId": 1,
    }, content_type="application/json", **_auth(alice))

    assert User.objects.count() == user_count_before
    assert Item.objects.count() == item_count_before
