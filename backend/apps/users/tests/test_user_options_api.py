"""Contract tests for ``GET /api/users/v1/users/options/`` (Task 2.5).

Originally mirrored ``services/user/app/api/v1/users.py`` one-for-one. Two
deliberate departures from that original are asserted here, both narrowing:

* **``query`` is required (min 2 chars).** The FastAPI version answered an
  empty query with the first 200 active accounts, so any authenticated user
  could page out the company directory — names and emails — from a route
  whose job is "let me pick the colleague I am already typing". ``limit``
  is capped at a picker-sized 20 for the same reason.
* **``email`` is withheld from non-elevated callers.** A picker needs a name
  to display, not a mailbox to harvest. Admin screens keep it, because they
  use it to tell namesakes apart.

Everything else is unchanged: active-only, case-insensitive matching across
first/last name, email, username and display_name, and no admin gate on the
route itself — a plain user can still search.
"""

import pytest
from django.test import Client

from apps.users.models import User, UserStatus
from htqweb.authn.jwt import issue_token_pair

BASE = "/api/users/v1"


def _mk(username: str, *, status=UserStatus.ACTIVE, **fields) -> User:
    u = User.objects.create(username=username, password="x", status=status,
                            **fields)
    u.set_password("S3cret!")
    u.save()
    return u


@pytest.fixture
def alice(db):
    return _mk("alice", email="alice@htq.test", first_name="Alice",
               last_name="Smith")


@pytest.fixture
def bob(db):
    return _mk("bob", email="bob@htq.test", first_name="Bob",
               last_name="Jones")


@pytest.fixture
def staff_user(db):
    return _mk("boss", email="boss@htq.test", first_name="Boss",
               last_name="Person", is_staff=True)


@pytest.fixture
def pending_user(db):
    return _mk("pendy", email="pendy@htq.test", status=UserStatus.PENDING,
               first_name="Pen", last_name="Ding")


@pytest.fixture
def suspended_user(db):
    return _mk("suspy", email="suspy@htq.test", status=UserStatus.SUSPENDED,
               first_name="Sus", last_name="Pended")


@pytest.fixture
def rejected_user(db):
    return _mk("rejy", email="rejy@htq.test", status=UserStatus.REJECTED,
               first_name="Rej", last_name="Ected")


def _auth(user) -> dict:
    token = issue_token_pair(user)["access"]
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


OPTION_FIELDS = {"id", "full_name", "email"}


@pytest.mark.django_db
def test_options_401_without_token(db):
    resp = Client().get(f"{BASE}/users/options/")
    assert resp.status_code == 401


# ── the search contract ─────────────────────────────────────────────────

@pytest.mark.django_db
def test_options_without_query_is_422(alice, bob):
    """No query, no directory. This is the whole point of the tightening."""
    resp = Client().get(f"{BASE}/users/options/", **_auth(alice))
    assert resp.status_code == 422
    assert "detail" in resp.json()


@pytest.mark.django_db
def test_options_one_character_query_is_422(alice):
    """A single letter matches most of the company — that is a dump with a
    filter on it, not a search."""
    resp = Client().get(f"{BASE}/users/options/?query=a", **_auth(alice))
    assert resp.status_code == 422


@pytest.mark.django_db
def test_options_200_shape(alice, bob):
    resp = Client().get(f"{BASE}/users/options/?query=alice", **_auth(alice))
    assert resp.status_code == 200
    body = resp.json()
    row = next(r for r in body if r["id"] == alice.id)
    assert set(row) == OPTION_FIELDS
    assert row["full_name"] == "Alice Smith"


@pytest.mark.django_db
def test_options_any_authenticated_user_can_call(bob, alice):
    """No admin gate — a plain (non-staff) user can still search."""
    resp = Client().get(f"{BASE}/users/options/?query=alice", **_auth(bob))
    assert resp.status_code == 200


# ── email exposure ──────────────────────────────────────────────────────

@pytest.mark.django_db
def test_email_is_hidden_from_regular_callers(alice, bob):
    resp = Client().get(f"{BASE}/users/options/?query=bob", **_auth(alice))
    row = next(r for r in resp.json() if r["id"] == bob.id)
    assert row["email"] == ""          # key kept, value withheld


@pytest.mark.django_db
def test_email_is_visible_to_elevated_callers(staff_user, bob):
    resp = Client().get(f"{BASE}/users/options/?query=bob", **_auth(staff_user))
    row = next(r for r in resp.json() if r["id"] == bob.id)
    assert row["email"] == "bob@htq.test"


# ── status filtering (unchanged) ────────────────────────────────────────

@pytest.mark.django_db
def test_options_excludes_pending(alice, pending_user):
    resp = Client().get(f"{BASE}/users/options/?query=ding", **_auth(alice))
    assert {row["id"] for row in resp.json()} == set()


@pytest.mark.django_db
def test_options_excludes_suspended(alice, suspended_user):
    resp = Client().get(f"{BASE}/users/options/?query=pended", **_auth(alice))
    assert {row["id"] for row in resp.json()} == set()


@pytest.mark.django_db
def test_options_excludes_rejected(alice, rejected_user):
    resp = Client().get(f"{BASE}/users/options/?query=ected", **_auth(alice))
    assert {row["id"] for row in resp.json()} == set()


# ── matching (unchanged) ────────────────────────────────────────────────

@pytest.mark.django_db
def test_options_query_filters_by_first_name_case_insensitive(alice, bob):
    resp = Client().get(f"{BASE}/users/options/?query=ALICE", **_auth(alice))
    assert {row["id"] for row in resp.json()} == {alice.id}


@pytest.mark.django_db
def test_options_query_filters_by_last_name(alice, bob):
    resp = Client().get(f"{BASE}/users/options/?query=jones", **_auth(alice))
    assert {row["id"] for row in resp.json()} == {bob.id}


@pytest.mark.django_db
def test_options_query_filters_by_email(alice, bob):
    resp = Client().get(f"{BASE}/users/options/?query=bob@htq", **_auth(alice))
    assert {row["id"] for row in resp.json()} == {bob.id}


@pytest.mark.django_db
def test_options_query_filters_by_username(alice, bob):
    resp = Client().get(f"{BASE}/users/options/?query=BOB", **_auth(alice))
    assert {row["id"] for row in resp.json()} == {bob.id}


@pytest.mark.django_db
def test_options_query_no_match_returns_empty(alice):
    resp = Client().get(f"{BASE}/users/options/?query=zzznomatchzzz",
                        **_auth(alice))
    assert resp.status_code == 200
    assert resp.json() == []


# ── limit bounds ────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_options_limit_respected(alice, bob):
    resp = Client().get(f"{BASE}/users/options/?query=htq&limit=1",
                        **_auth(alice))
    assert resp.status_code == 200
    assert len(resp.json()) == 1


@pytest.mark.django_db
def test_options_limit_zero_422(alice):
    resp = Client().get(f"{BASE}/users/options/?query=alice&limit=0",
                        **_auth(alice))
    assert resp.status_code == 422


@pytest.mark.django_db
def test_options_limit_above_cap_is_422(alice):
    """The old ceiling was 500; a picker does not need 500 rows, and asking
    for them is the directory dump wearing a query string."""
    resp = Client().get(f"{BASE}/users/options/?query=alice&limit=21",
                        **_auth(alice))
    assert resp.status_code == 422


@pytest.mark.django_db
def test_options_limit_at_cap_ok(alice):
    resp = Client().get(f"{BASE}/users/options/?query=alice&limit=20",
                        **_auth(alice))
    assert resp.status_code == 200


@pytest.mark.django_db
def test_options_limit_1_ok(alice):
    resp = Client().get(f"{BASE}/users/options/?query=alice&limit=1",
                        **_auth(alice))
    assert resp.status_code == 200


@pytest.mark.django_db
def test_options_full_name_falls_back_to_username(db, alice):
    u = _mk("noname", email="noname@htq.test")
    resp = Client().get(f"{BASE}/users/options/?query=noname", **_auth(alice))
    row = next(r for r in resp.json() if r["id"] == u.id)
    assert row["full_name"] == "noname"
