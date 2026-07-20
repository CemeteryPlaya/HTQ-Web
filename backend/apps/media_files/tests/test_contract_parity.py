"""Contract-parity tests for the media domain (Task 3.4).

PROVENANCE — read this before touching the fixtures in ``tests/fixtures/``:
the FastAPI media-service is not running in this environment (no live stack
— see the Task 1.8/3.4 briefs / ``backend/README-tests.md``), so none of the
shapes below were captured from a live response. They were derived by
reading the Pydantic response models directly:

  - ``services/media/app/schemas/file.py`` :: ``FileMetadataRead``, ``SignedUrlResponse``

A later engineer who spins up the real FastAPI stack should replace these
JSON fixtures with actually-captured live responses (the shape-checking
helpers below can stay as-is) — each fixture's ``"source"`` key says exactly
this, so nobody mistakes "derived from schema" for "verified against the
running original".

The point of these tests is DRIFT DETECTION, not characterization of
whatever Django happens to return today: assertions check the field NAMES
and TYPES pulled from the FastAPI schemas, so a future change to
``apps/media_files/schemas.py`` that renames/drops/retypes a field the
frontend depends on fails a test here — even if today's Django output
already looks "reasonable" on its own.

``FileVariantRead`` (also in ``schemas/file.py``) is deliberately NOT given
its own fixture: no FastAPI route returns it directly — it only exists to
type ``FileMetadataRead.variants`` in the SQLAlchemy relationship sense,
while the actual wire shape flattens variants into ``dict[str, str]``
(``{variant_name: url}``, see ``serialize_file`` in both the FastAPI source
and ``apps/media_files/schemas.py``). That flattened shape is asserted
directly in ``test_upload_response_variants_map_is_name_to_url`` below.

``list_files`` (``GET /files/``, admin-only) responds ``list[FileMetadataRead]``
— same per-entry contract as the upload response, asserted per-entry below
rather than duplicating the fixture.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from django.test import Client
from PIL import Image

from apps.media_files import tasks, views
from apps.media_files.models import FileMetadata
from apps.media_files.services import upload_service
from apps.users.models import User, UserStatus
from htqweb.authn.jwt import issue_token_pair

FIXTURES = Path(__file__).parent / "fixtures"
BASE = "/api/media/v1/files"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _check_type(value, expected: str) -> bool:
    """``expected`` is a ``|``-joined list of: int, str, bool, list, dict,
    null. (Extends cms's ``test_contract_parity.py`` helper of the same
    name with ``dict`` — media's ``FileMetadataRead.variants`` is the first
    fixture that needs it; kept as a local copy rather than a shared
    utility, same "deliberately duplicated per app" convention the rest of
    this codebase follows for test helpers.)"""
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


class _RecordingStorage:
    def __init__(self):
        self.objects: dict[str, tuple[bytes, str | None]] = {}

    def save(self, path, data, content_type=None):
        self.objects[path] = (data, content_type)

    def open(self, path, byte_range=None):
        return self.objects[path][0]

    def delete(self, path):
        self.objects.pop(path, None)

    def exists(self, path):
        return path in self.objects

    def size(self, path):
        return len(self.objects[path][0])


@pytest.fixture
def fake_storage(monkeypatch):
    storage = _RecordingStorage()
    monkeypatch.setattr(upload_service, "get_storage", lambda bucket=None: storage)
    monkeypatch.setattr(tasks, "get_storage", lambda bucket=None: storage)
    monkeypatch.setattr(views, "get_storage", lambda bucket=None: storage)
    return storage


@pytest.fixture
def user(db):
    u = User.objects.create(username="parity", email="parity@htq.test",
                             status=UserStatus.ACTIVE)
    u.set_password("S3cret!")
    u.save()
    return u


@pytest.fixture
def admin(db):
    u = User.objects.create(username="parity-admin", email="parity-admin@htq.test",
                             status=UserStatus.ACTIVE, is_staff=True)
    u.set_password("S3cret!")
    u.save()
    return u


def _auth(user) -> dict:
    token = issue_token_pair(user)["access"]
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


def _png_bytes(size=(64, 64), color=(5, 6, 7)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


# ── FileMetadataRead — upload response ───────────────────────────────────────


@pytest.mark.django_db
def test_upload_response_matches_file_metadata_read_schema_shape(fake_storage, user):
    """Shape derived from
    services/media/app/schemas/file.py::FileMetadataRead — NOT a live
    FastAPI capture (see module docstring)."""
    contract = _load("file_metadata_read.json")

    resp = Client().post(
        f"{BASE}/",
        data={"file": _uploaded_file("notes.txt", b"hello", "text/plain")},
        **_auth(user),
    )
    assert resp.status_code == 201
    _assert_matches_contract(resp.json(), contract)


@pytest.mark.django_db
def test_upload_response_variants_map_is_name_to_url(fake_storage, user):
    """``variants`` isn't just "a dict" (the generic contract check above)
    — assert its concrete shape: {variant_name: url_string}, matching
    ``serialize_file`` in both the FastAPI source and the Django port."""
    resp = Client().post(
        f"{BASE}/",
        data={"file": _uploaded_file("avatar.png", _png_bytes(), "image/png"),
              "scope": "avatar"},
        **_auth(user),
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["variants"], "avatar scope has variants configured — map must be non-empty"
    for name, url in body["variants"].items():
        assert isinstance(name, str)
        assert isinstance(url, str)
        assert url == f"{BASE}/{body['id']}/{name}"


# ── FileMetadataRead — list response (admin, GET /files/) ───────────────────


@pytest.mark.django_db
def test_list_response_entries_match_file_metadata_read_schema_shape(fake_storage, user, admin):
    contract = _load("file_metadata_read.json")

    upload = Client().post(
        f"{BASE}/",
        data={"file": _uploaded_file("notes.txt", b"hello", "text/plain")},
        **_auth(user),
    )
    assert upload.status_code == 201

    resp = Client().get(f"{BASE}/", **_auth(admin))
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list) and body
    for entry in body:
        _assert_matches_contract(entry, contract)


# ── SignedUrlResponse — POST /{file_id}/sign ─────────────────────────────────


@pytest.mark.django_db
def test_signed_url_response_matches_schema_shape_for_private_file(fake_storage, user):
    """Shape derived from
    services/media/app/schemas/file.py::SignedUrlResponse — NOT a live
    FastAPI capture (see module docstring)."""
    contract = _load("signed_url_response.json")
    meta = FileMetadata.objects.create(
        path="p", original_filename="p.txt", size=1, mime="text/plain",
        is_public=False, kind="document", scope="generic", owner_id=user.id,
    )

    resp = Client().post(f"{BASE}/{meta.id}/sign", **_auth(user))
    assert resp.status_code == 200
    _assert_matches_contract(resp.json(), contract)


@pytest.mark.django_db
def test_signed_url_response_matches_schema_shape_for_public_file(fake_storage, user):
    """Public files go through the same ``SignedUrlResponse`` shape (plain
    URL + a cache-busting ``exp``) — asserted against the same fixture as
    the private case, not a bespoke one, same as cms's
    ``ContactRequestRead`` reuse across create/get/reply."""
    contract = _load("signed_url_response.json")
    meta = FileMetadata.objects.create(
        path="p", original_filename="p.txt", size=1, mime="text/plain",
        is_public=True, kind="document", scope="generic", owner_id=user.id,
    )

    resp = Client().post(f"{BASE}/{meta.id}/sign", **_auth(user))
    assert resp.status_code == 200
    _assert_matches_contract(resp.json(), contract)


def _uploaded_file(name: str, content: bytes, content_type: str):
    from django.core.files.uploadedfile import SimpleUploadedFile

    return SimpleUploadedFile(name, content, content_type=content_type)
