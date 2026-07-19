"""Contract tests for ``GET /api/users/v1/users/options/`` (Task 2.5).

Mirrors ``services/user/app/api/v1/users.py`` (the FastAPI original):
active-only picker list, ``query`` filters case-insensitively across
first/last name, email and username, ``limit`` defaults to 200 and is
bounded 1..500 (out-of-range 422s, matching FastAPI's
``Query(ge=1, le=500)``). Any authenticated user may call this — no admin
gate.
"""

import pytest
from django.test import Client

from apps.users.models import User, UserStatus
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


@pytest.fixture
def pending_user(db):
    u = User.objects.create(username="pendy", email="pendy@htq.test", password="x",
                            status=UserStatus.PENDING, first_name="Pen", last_name="Ding")
    u.set_password("S3cret!")
    u.save()
    return u


@pytest.fixture
def suspended_user(db):
    u = User.objects.create(username="suspy", email="suspy@htq.test", password="x",
                            status=UserStatus.SUSPENDED, first_name="Sus", last_name="Pended")
    u.set_password("S3cret!")
    u.save()
    return u


@pytest.fixture
def rejected_user(db):
    u = User.objects.create(username="rejy", email="rejy@htq.test", password="x",
                            status=UserStatus.REJECTED, first_name="Rej", last_name="Ected")
    u.set_password("S3cret!")
    u.save()
    return u


def _auth(user) -> dict:
    token = issue_token_pair(user)["access"]
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


OPTION_FIELDS = {"id", "full_name", "email"}


@pytest.mark.django_db
def test_options_401_without_token(db):
    resp = Client().get(f"{BASE}/users/options/")
    assert resp.status_code == 401


@pytest.mark.django_db
def test_options_200_shape(alice, bob):
    resp = Client().get(f"{BASE}/users/options/", **_auth(alice))
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) >= 2
    row = next(r for r in body if r["id"] == alice.id)
    assert set(row) == OPTION_FIELDS
    assert row["full_name"] == "Alice Smith"
    assert row["email"] == "alice@htq.test"


@pytest.mark.django_db
def test_options_any_authenticated_user_can_call(bob, alice):
    """No admin gate — a plain (non-staff) user can call this."""
    resp = Client().get(f"{BASE}/users/options/", **_auth(bob))
    assert resp.status_code == 200


@pytest.mark.django_db
def test_options_excludes_pending(alice, pending_user):
    resp = Client().get(f"{BASE}/users/options/", **_auth(alice))
    ids = {row["id"] for row in resp.json()}
    assert pending_user.id not in ids
    assert alice.id in ids


@pytest.mark.django_db
def test_options_excludes_suspended(alice, suspended_user):
    resp = Client().get(f"{BASE}/users/options/", **_auth(alice))
    ids = {row["id"] for row in resp.json()}
    assert suspended_user.id not in ids


@pytest.mark.django_db
def test_options_excludes_rejected(alice, rejected_user):
    resp = Client().get(f"{BASE}/users/options/", **_auth(alice))
    ids = {row["id"] for row in resp.json()}
    assert rejected_user.id not in ids


@pytest.mark.django_db
def test_options_query_filters_by_first_name_case_insensitive(alice, bob):
    resp = Client().get(f"{BASE}/users/options/?query=ALICE", **_auth(alice))
    body = resp.json()
    assert {row["id"] for row in body} == {alice.id}


@pytest.mark.django_db
def test_options_query_filters_by_last_name(alice, bob):
    resp = Client().get(f"{BASE}/users/options/?query=jones", **_auth(alice))
    body = resp.json()
    assert {row["id"] for row in body} == {bob.id}


@pytest.mark.django_db
def test_options_query_filters_by_email(alice, bob):
    resp = Client().get(f"{BASE}/users/options/?query=bob@htq", **_auth(alice))
    body = resp.json()
    assert {row["id"] for row in body} == {bob.id}


@pytest.mark.django_db
def test_options_query_filters_by_username(alice, bob):
    resp = Client().get(f"{BASE}/users/options/?query=BOB", **_auth(alice))
    body = resp.json()
    assert {row["id"] for row in body} == {bob.id}


@pytest.mark.django_db
def test_options_query_no_match_returns_empty(alice):
    resp = Client().get(f"{BASE}/users/options/?query=zzznomatchzzz", **_auth(alice))
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.django_db
def test_options_limit_respected(alice, bob):
    resp = Client().get(f"{BASE}/users/options/?limit=1", **_auth(alice))
    assert resp.status_code == 200
    assert len(resp.json()) == 1


@pytest.mark.django_db
def test_options_limit_default_200(alice):
    resp = Client().get(f"{BASE}/users/options/", **_auth(alice))
    assert resp.status_code == 200
    # Just a handful of active users exist in this test — default 200 must
    # not truncate them.
    assert len(resp.json()) >= 1


@pytest.mark.django_db
def test_options_limit_zero_422(alice):
    resp = Client().get(f"{BASE}/users/options/?limit=0", **_auth(alice))
    assert resp.status_code == 422


@pytest.mark.django_db
def test_options_limit_501_422(alice):
    resp = Client().get(f"{BASE}/users/options/?limit=501", **_auth(alice))
    assert resp.status_code == 422


@pytest.mark.django_db
def test_options_limit_500_ok(alice):
    resp = Client().get(f"{BASE}/users/options/?limit=500", **_auth(alice))
    assert resp.status_code == 200


@pytest.mark.django_db
def test_options_limit_1_ok(alice):
    resp = Client().get(f"{BASE}/users/options/?limit=1", **_auth(alice))
    assert resp.status_code == 200


@pytest.mark.django_db
def test_options_full_name_falls_back_to_username(db, alice):
    u = User.objects.create(username="noname", email="noname@htq.test", password="x",
                            status=UserStatus.ACTIVE)
    u.set_password("S3cret!")
    u.save()
    resp = Client().get(f"{BASE}/users/options/", **_auth(alice))
    row = next(r for r in resp.json() if r["id"] == u.id)
    assert row["full_name"] == "noname"
