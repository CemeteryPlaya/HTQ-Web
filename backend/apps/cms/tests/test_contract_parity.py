"""Contract-parity tests for the cms domain (Task 1.8, Part B).

PROVENANCE — read this before touching the fixtures in ``tests/fixtures/``:
the FastAPI cms-service is not running in this environment (no live stack —
see the Task 1.8 brief / ``backend/README-tests.md``), so none of the shapes
below were captured from a live response. They were derived by reading the
Pydantic response models directly:

  - ``services/cms/app/schemas/contact_request.py`` :: ``ContactRequestRead``, ``ContactRequestStats``
  - ``services/cms/app/schemas/conference.py``       :: ``ConferenceConfig``, ``IceServer``

A later engineer who spins up the real FastAPI stack should replace these
JSON fixtures with actually-captured live responses (the shape-checking
helpers below can stay as-is) — each fixture's ``"source"`` key says exactly
this, so nobody mistakes "derived from schema" for "verified against the
running original".

The point of these tests is DRIFT DETECTION, not characterization of
whatever Django happens to return today: assertions check the field NAMES
and TYPES pulled from the FastAPI schemas, so a future change to
``apps/cms/schemas.py`` that renames/drops/retypes a field the React
frontend depends on fails a test here — even if today's Django output
already looks "reasonable" on its own.
"""

from __future__ import annotations

import json
from pathlib import Path

import jwt as pyjwt
import pytest
from django.conf import settings
from django.test import Client

from apps.cms.models import ContactRequest

FIXTURES = Path(__file__).parent / "fixtures"
BASE = "/api/cms/v1"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _admin_token():
    claims = {
        "user_id": 9, "username": "admin", "email": "admin@htq.test",
        "is_staff": True, "is_superuser": True, "is_admin": True,
        "token_type": "access", "iat": 1, "exp": 9_999_999_999,
        "iss": "htqweb-auth", "sub": "9",
    }
    return pyjwt.encode(claims, settings.JWT_SECRET, algorithm="HS256")


def _auth_header() -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {_admin_token()}"}


def _check_type(value, expected: str) -> bool:
    """``expected`` is a ``|``-joined list of: int, str, bool, list, null."""
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


# ── ContactRequestRead ───────────────────────────────────────────────────────


@pytest.mark.django_db
def test_contact_request_read_matches_fastapi_schema_shape():
    """Shape derived from
    services/cms/app/schemas/contact_request.py::ContactRequestRead — NOT a
    live FastAPI capture (see module docstring)."""
    contract = _load("contact_request_read.json")
    entry = ContactRequest.objects.create(email="parity@example.com", first_name="P")
    resp = Client().get(f"{BASE}/contact-requests/{entry.id}", **_auth_header())
    assert resp.status_code == 200
    _assert_matches_contract(resp.json(), contract)


@pytest.mark.django_db
def test_contact_request_read_create_response_matches_same_schema():
    """POST / and GET /{id} share ``ContactRequestRead`` in the FastAPI
    original (both routers declare the same ``response_model``) — assert the
    create response against the same contract, not a bespoke one."""
    contract = _load("contact_request_read.json")
    resp = Client().post(
        f"{BASE}/contact-requests/",
        data=json.dumps({"first_name": "A", "last_name": "B",
                          "email": "create-parity@example.com", "message": "hi"}),
        content_type="application/json",
    )
    assert resp.status_code == 201
    _assert_matches_contract(resp.json(), contract)


@pytest.mark.django_db
def test_contact_request_read_reply_response_matches_same_schema():
    """POST /{id}/reply also returns ``ContactRequestRead`` in the FastAPI
    original."""
    contract = _load("contact_request_read.json")
    entry = ContactRequest.objects.create(email="reply-parity@example.com")
    resp = Client().post(
        f"{BASE}/contact-requests/{entry.id}/reply",
        data=json.dumps({"reply_message": "we got it"}),
        content_type="application/json",
        **_auth_header(),
    )
    assert resp.status_code == 200
    _assert_matches_contract(resp.json(), contract)


# ── ContactRequestStats ──────────────────────────────────────────────────────


@pytest.mark.django_db
def test_contact_request_stats_matches_fastapi_schema_shape():
    """Shape derived from
    services/cms/app/schemas/contact_request.py::ContactRequestStats — NOT a
    live FastAPI capture (see module docstring)."""
    contract = _load("contact_request_stats.json")
    resp = Client().get(f"{BASE}/contact-requests/stats", **_auth_header())
    assert resp.status_code == 200
    _assert_matches_contract(resp.json(), contract)


# ── ConferenceConfig ─────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_conference_config_matches_fastapi_schema_shape_plus_intentional_enabled_field():
    """Shape derived from
    services/cms/app/schemas/conference.py::ConferenceConfig — NOT a live
    FastAPI capture (see module docstring).

    ``enabled`` is NOT part of the FastAPI ``ConferenceConfig`` — it is
    Django's one intentional addition beyond the port (Task 1.5, see
    ``apps/cms/schemas.py``'s ``ConferenceConfig`` docstring), so it is
    passed here as an explicitly allowed extra key rather than folded into
    the ported contract.
    """
    contract = _load("conference_config.json")
    resp = Client().get(f"{BASE}/conference/config", **_auth_header())
    assert resp.status_code == 200
    body = resp.json()
    _assert_matches_contract(body, contract, extra_allowed=frozenset({"enabled"}))
    assert isinstance(body["enabled"], bool)


@pytest.mark.django_db
def test_conference_config_ice_servers_match_ice_server_schema():
    """Shape derived from
    services/cms/app/schemas/conference.py::IceServer — NOT a live FastAPI
    capture (see module docstring)."""
    contract = _load("ice_server.json")
    resp = Client().get(f"{BASE}/conference/config", **_auth_header())
    assert resp.status_code == 200
    servers = resp.json()["ice_servers"]
    assert isinstance(servers, list)
    assert servers  # settings ship two STUN defaults (see test_conference_config.py)
    for server in servers:
        _assert_matches_contract(server, contract)
