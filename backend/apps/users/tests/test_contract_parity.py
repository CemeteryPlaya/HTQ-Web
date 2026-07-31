"""Contract-parity tests for the users domain (Task 2.7, Part D).

PROVENANCE — read this before touching the fixtures in ``tests/fixtures/``:
the FastAPI user-service is not running in this environment (no live stack —
see the Task 2.7 brief / ``backend/README-tests.md``), so none of the shapes
below were captured from a live response. They were derived by reading the
Pydantic response models directly. Note that (unlike cms) the FastAPI
original does NOT keep these in a separate ``services/user/app/schemas/``
package — they're declared inline in each router module (see
``apps/users/schemas.py``'s own module docstring, which notes the same
thing about this Django port's copies):

  - ``services/user/app/api/v1/auth.py``         :: ``TokenResponse``, ``TokenRefreshResponse``
  - ``services/user/app/api/v1/profile.py``      :: ``ProfileResponse``
  - ``services/user/app/api/v1/admin.py``        :: ``AdminUserResponse``
  - ``services/user/app/api/v1/registration.py`` :: ``PendingUserResponse``
  - ``services/user/app/api/v1/items.py``        :: ``ItemResponse``
  - ``services/user/app/api/v1/users.py``        :: ``UserOption``

A later engineer who spins up the real FastAPI stack should replace these
JSON fixtures with actually-captured live responses (the shape-checking
helpers below can stay as-is) — each fixture's ``"source"`` key says exactly
this, so nobody mistakes "derived from schema" for "verified against the
running original".

The point of these tests is DRIFT DETECTION, not characterization of
whatever Django happens to return today: assertions check the field NAMES
and TYPES pulled from the FastAPI schemas, so a future change to
``apps/users/schemas.py`` (or the service functions that feed it) that
renames/drops/retypes a field the React frontend depends on fails a test
here — even if today's Django output already looks "reasonable" on its own.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from django.test import Client

from apps.users.models import User, UserStatus
from htqweb.authn.jwt import issue_token_pair

FIXTURES = Path(__file__).parent / "fixtures"
BASE = "/api/users/v1"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _make_user(**kwargs) -> User:
    defaults = dict(status=UserStatus.ACTIVE)
    defaults.update(kwargs)
    u = User.objects.create(**defaults)
    u.set_password("S3cret!")
    u.save()
    return u


def _auth(user) -> dict:
    token = issue_token_pair(user)["access"]
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


def _check_type(value, expected: str) -> bool:
    """``expected`` is a ``|``-joined list of: int, str, bool, list, dict,
    null. Extends the cms precedent (``apps/cms/tests/test_contract_parity.
    py::_check_type``) with a ``dict`` option — users's ``ProfileResponse``/
    ``AdminUserResponse`` carry nested dict fields (``avatar``, ``settings``)
    that cms's contracts never needed."""
    for opt in expected.split("|"):
        if opt == "null" and value is None:
            return True
        if opt == "int" and isinstance(value, int) and not isinstance(value, bool):
            return True
        if opt == "str" and isinstance(value, str):
            return True
        if opt == "bool" and isinstance(value, bool):
            return True
        if opt == "list" and isinstance(value, list):
            return True
        if opt == "dict" and isinstance(value, dict):
            return True
    return False


def _assert_matches_contract(body: dict, contract: dict, *, extra_allowed: frozenset = frozenset()):
    fields = contract["fields"]
    expected_keys = set(fields) | set(extra_allowed)
    assert set(body) == expected_keys, (
        f"top-level keys drifted from {contract['source']}: "
        f"got {sorted(body)}, expected {sorted(expected_keys)}"
    )
    for key, expected_type in fields.items():
        assert _check_type(body[key], expected_type), (
            f"{key!r} = {body[key]!r} does not match expected type "
            f"{expected_type!r} derived from {contract['source']}"
        )


# ── TokenResponse / TokenRefreshResponse ─────────────────────────────────────


@pytest.mark.django_db
def test_token_response_matches_fastapi_schema_shape():
    """Shape derived from services/user/app/api/v1/auth.py::TokenResponse —
    NOT a live FastAPI capture (see module docstring)."""
    contract = _load("token_response.json")
    _make_user(username="tok", email="tok@htq.test")
    resp = Client().post(
        f"{BASE}/token/",
        data=json.dumps({"email": "tok@htq.test", "password": "S3cret!"}),
        content_type="application/json",
    )
    assert resp.status_code == 200
    _assert_matches_contract(resp.json(), contract)


@pytest.mark.django_db
def test_token_refresh_response_matches_fastapi_schema_shape():
    """Shape derived from
    services/user/app/api/v1/auth.py::TokenRefreshResponse — NOT a live
    FastAPI capture (see module docstring)."""
    contract = _load("token_refresh_response.json")
    user = _make_user(username="tokr", email="tokr@htq.test")
    pair = issue_token_pair(user)
    resp = Client().post(
        f"{BASE}/token/refresh/",
        data=json.dumps({"refresh": pair["refresh"]}),
        content_type="application/json",
    )
    assert resp.status_code == 200
    _assert_matches_contract(resp.json(), contract)


# ── ProfileResponse ──────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_profile_response_matches_fastapi_schema_shape():
    """Shape derived from
    services/user/app/api/v1/profile.py::ProfileResponse — NOT a live
    FastAPI capture (see module docstring). Covers both the snake_case and
    camelCase name duplicates and the structured ``avatar`` block."""
    contract = _load("profile_response.json")
    user = _make_user(username="prof", email="prof@htq.test",
                       first_name="Pro", last_name="File")
    resp = Client().get(f"{BASE}/profile/me", **_auth(user))
    assert resp.status_code == 200
    body = resp.json()
    _assert_matches_contract(body, contract)
    # camelCase/snake_case duplicates must actually agree, not just both exist.
    assert body["firstName"] == body["first_name"] == "Pro"
    assert body["lastName"] == body["last_name"] == "File"
    assert body["avatarUrl"] == body["avatar_url"] is None
    assert body["avatar"] is None  # no avatar set — avatar_payload() returns None


@pytest.mark.django_db
def test_profile_response_avatar_block_matches_contract_when_present():
    """``avatar`` is a nested dict (``{id, url, variants}``), not a bare
    string — the FastAPI schema types it ``dict | None``, so a present
    avatar must still validate as a dict under the profile contract."""
    contract = _load("profile_response.json")
    user = _make_user(username="profav", email="profav@htq.test",
                       avatar_url="https://i.pravatar.cc/150")
    resp = Client().get(f"{BASE}/profile/me", **_auth(user))
    assert resp.status_code == 200
    body = resp.json()
    _assert_matches_contract(body, contract)
    assert isinstance(body["avatar"], dict)
    assert set(body["avatar"]) == {"id", "url", "variants"}


# ── AdminUserResponse ─────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_admin_user_response_matches_fastapi_schema_shape():
    """Shape derived from
    services/user/app/api/v1/admin.py::AdminUserResponse — NOT a live
    FastAPI capture (see module docstring)."""
    contract = _load("admin_user_response.json")
    admin = _make_user(username="adminp", email="adminp@htq.test",
                       is_staff=True, is_superuser=True)
    _make_user(username="listed", email="listed@htq.test", first_name="Lis", last_name="Ted")
    resp = Client().get(f"{BASE}/admin/users/", **_auth(admin))
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list) and body
    for row in body:
        _assert_matches_contract(row, contract)


# ── PendingUserResponse ───────────────────────────────────────────────────────


@pytest.mark.django_db
def test_pending_user_response_matches_fastapi_schema_shape():
    """Shape derived from
    services/user/app/api/v1/registration.py::PendingUserResponse — NOT a
    live FastAPI capture (see module docstring)."""
    contract = _load("pending_user_response.json")
    admin = _make_user(username="adminpend", email="adminpend@htq.test",
                       is_staff=True, is_superuser=True)
    _make_user(username="waiting", email="waiting@htq.test", status=UserStatus.PENDING,
               display_name="Waiting Person")
    resp = Client().get(f"{BASE}/pending-registrations/", **_auth(admin))
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list) and body
    for row in body:
        _assert_matches_contract(row, contract)


# ── UserOption ────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_user_option_matches_fastapi_schema_shape():
    """Shape derived from services/user/app/api/v1/users.py::UserOption —
    NOT a live FastAPI capture (see module docstring)."""
    contract = _load("user_option.json")
    caller = _make_user(username="optioncaller", email="optioncaller@htq.test",
                        first_name="Opt", last_name="Ion")
    # ``query`` is required now (min 2 chars); the response SHAPE is what
    # this test pins, and that is unchanged — see test_user_options_api.py.
    resp = Client().get(f"{BASE}/users/options/?query=optioncaller",
                        **_auth(caller))
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list) and body
    for row in body:
        _assert_matches_contract(row, contract)
