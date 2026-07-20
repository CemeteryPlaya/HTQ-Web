"""R5 remediation: scope write-authorization seam (decision Д1).

Before this seam, ``scope`` was free-text, unauthorized client input —
``views.py``'s ``upload_file`` did ``scope = request.POST.get("scope") or
"generic"`` with no check at all, so ANY authenticated user could write into
``hr_doc``/``hr_department``/``task_attachment`` (scopes belonging to
not-yet-migrated privileged/owned domains, see ``scope_policy.py``'s
``RESTRICTED_SCOPES``). Nothing reads by scope yet, so this was unexploited,
but the fork had to close before hr/task migrate.

Covers both entry points that write a scope:
- the HTTP endpoint (``POST /api/media/v1/files/``), authorized off
  ``request.token.is_elevated``;
- ``interface.store_file``, authorized off the explicit
  ``internal_authorized`` kwarg (no JWT to read at that layer).

Interim rule (NOT final): restricted scopes require ``is_elevated`` for now;
open scopes (avatar/news/chat/generic) are unrestricted; an unknown scope
(e.g. the frontend's ``cms-news``) is not rejected — it falls back to the
``generic`` policy with a logged warning, preserving existing frontend
behaviour.
"""

from __future__ import annotations

import logging

import pytest
from django.core.exceptions import PermissionDenied
from django.test import Client

from apps.media_files import interface
from apps.media_files.models import FileMetadata
from apps.media_files.services import upload_service
from apps.media_files.services.scope_policy import (
    RESTRICTED_SCOPES,
    authorize_scope_write,
    get_policy,
    normalize_scope,
)
from apps.users.models import User, UserStatus
from htqweb.authn.jwt import issue_token_pair

BASE = "/api/media/v1/files/"


# ─── fixtures (mirrors test_upload_api.py) ──────────────────────────────────


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
    return storage


@pytest.fixture
def user(db):
    u = User.objects.create(
        username="uploader", email="uploader@htq.test", password="x",
        status=UserStatus.ACTIVE,
    )
    u.set_password("S3cret!")
    u.save()
    return u


@pytest.fixture
def elevated_user(db):
    u = User.objects.create(
        username="staffer", email="staffer@htq.test", password="x",
        status=UserStatus.ACTIVE, is_staff=True,
    )
    u.set_password("S3cret!")
    u.save()
    return u


def _auth(user) -> dict:
    token = issue_token_pair(user)["access"]
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


def _upload(client, user, *, filename, content, content_type, scope):
    data = {
        "file": _upload_file(filename, content, content_type),
        "scope": scope,
    }
    return client.post(BASE, data=data, **_auth(user))


def _upload_file(filename, content, content_type):
    from django.core.files.uploadedfile import SimpleUploadedFile
    return SimpleUploadedFile(filename, content, content_type=content_type)


def _pdf_bytes() -> bytes:
    return b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\nminimal filler bytes"


def _png_bytes() -> bytes:
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (16, 16), (10, 20, 30)).save(buf, format="PNG")
    return buf.getvalue()


# ─── pure seam unit tests ────────────────────────────────────────────────────


def test_restricted_scopes_are_exactly_the_three_unmigrated_domains():
    assert RESTRICTED_SCOPES == {"hr_doc", "hr_department", "task_attachment"}


@pytest.mark.parametrize("scope", sorted(RESTRICTED_SCOPES))
def test_authorize_scope_write_denies_restricted_scope_when_not_elevated(scope):
    with pytest.raises(PermissionDenied):
        authorize_scope_write(scope, is_elevated=False)


@pytest.mark.parametrize("scope", sorted(RESTRICTED_SCOPES))
def test_authorize_scope_write_allows_restricted_scope_when_elevated(scope):
    authorize_scope_write(scope, is_elevated=True)  # must not raise


@pytest.mark.parametrize("scope", ["avatar", "news", "chat", "generic"])
def test_authorize_scope_write_allows_open_scope_regardless_of_elevation(scope):
    authorize_scope_write(scope, is_elevated=False)  # must not raise
    authorize_scope_write(scope, is_elevated=True)  # must not raise


def test_authorize_scope_write_unknown_scope_logs_warning_and_is_allowed(caplog):
    with caplog.at_level(logging.WARNING, logger="apps.media_files.services.scope_policy"):
        authorize_scope_write("cms-news", is_elevated=False)  # must not raise
    assert any(
        "unknown upload scope" in record.getMessage() and "cms-news" in record.getMessage()
        for record in caplog.records
    )


# ─── normalization: a case/whitespace variant of a restricted scope must NOT
#     slip through the unknown→generic branch (final-review R5 minor) ──────────


@pytest.mark.parametrize("variant", ["HR_DOC", "hr_doc ", " Hr_Doc", "HR_DEPARTMENT", "Task_Attachment"])
def test_authorize_scope_write_denies_case_or_whitespace_variant_of_restricted(variant):
    """RED before the fix: these missed the case-sensitive KNOWN_SCOPES/
    RESTRICTED_SCOPES exact match, fell into the unknown→generic branch, and
    were silently allowed. Normalizing (strip+lower) canonicalises them so the
    restricted check catches them."""
    with pytest.raises(PermissionDenied):
        authorize_scope_write(variant, is_elevated=False)


@pytest.mark.parametrize("variant", ["HR_DOC", "hr_doc "])
def test_authorize_scope_write_allows_restricted_variant_when_elevated(variant):
    authorize_scope_write(variant, is_elevated=True)  # must not raise


def test_normalize_scope_strips_and_lowercases():
    assert normalize_scope("  HR_DOC ") == "hr_doc"
    assert normalize_scope("Avatar") == "avatar"
    assert normalize_scope(None) == ""
    assert normalize_scope("cms-news") == "cms-news"


def test_get_policy_matches_canonical_variant():
    # A case/whitespace variant of a real scope resolves to that scope's
    # policy, not the generic fallback.
    assert get_policy("HR_DOC ").name == "hr_doc"
    assert get_policy("AVATAR").name == "avatar"
    # A genuinely unknown scope still falls back to generic.
    assert get_policy("cms-news").name == "generic"


@pytest.mark.django_db
def test_http_upload_restricted_variant_by_non_elevated_is_403(fake_storage, user):
    """The whole chain: a crafted 'HR_DOC' scope from a non-elevated user is
    rejected at the HTTP endpoint, not stored."""
    resp = _upload(
        Client(), user,
        filename="handbook.pdf", content=_pdf_bytes(), content_type="application/pdf",
        scope="HR_DOC",
    )
    assert resp.status_code == 403
    assert not FileMetadata.objects.exists()


@pytest.mark.django_db
def test_http_upload_stores_canonical_scope(fake_storage, user):
    """An open-scope upload with a case variant is stored under the canonical
    lowercase scope, so a future read side can match on the exact string."""
    resp = _upload(
        Client(), user,
        filename="a.png", content=_png_bytes(), content_type="image/png",
        scope="AVATAR",
    )
    assert resp.status_code == 201
    meta = FileMetadata.objects.get()
    assert meta.scope == "avatar"
    assert meta.path.startswith("avatar/")  # storage path is canonical too


# ─── HTTP endpoint ───────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_hr_doc_upload_by_non_elevated_user_is_403(fake_storage, user):
    """RED proof (pre-fix): this returned 201 and created a FileMetadata row
    for ANY authenticated user — see R5-report.md for the pre-fix run."""
    resp = _upload(
        Client(), user,
        filename="handbook.pdf", content=_pdf_bytes(), content_type="application/pdf",
        scope="hr_doc",
    )
    assert resp.status_code == 403
    assert not FileMetadata.objects.exists()


@pytest.mark.django_db
def test_hr_doc_upload_by_elevated_user_is_201(fake_storage, elevated_user):
    resp = _upload(
        Client(), elevated_user,
        filename="handbook.pdf", content=_pdf_bytes(), content_type="application/pdf",
        scope="hr_doc",
    )
    assert resp.status_code == 201
    assert FileMetadata.objects.filter(scope="hr_doc").exists()


@pytest.mark.django_db
def test_hr_department_upload_by_non_elevated_user_is_403(fake_storage, user):
    resp = _upload(
        Client(), user,
        filename="dept.jpg", content=_png_bytes(), content_type="image/png",
        scope="hr_department",
    )
    assert resp.status_code == 403
    assert not FileMetadata.objects.exists()


@pytest.mark.django_db
def test_task_attachment_upload_by_non_elevated_user_is_403(fake_storage, user):
    resp = _upload(
        Client(), user,
        filename="attach.png", content=_png_bytes(), content_type="image/png",
        scope="task_attachment",
    )
    assert resp.status_code == 403
    assert not FileMetadata.objects.exists()


@pytest.mark.django_db
@pytest.mark.parametrize("scope,filename,content,content_type", [
    ("avatar", "me.png", None, "image/png"),
    ("news", "cover.png", None, "image/png"),
    ("chat", "thing.bin", b"arbitrary bytes", "application/vnd.custom"),
    ("generic", "notes.txt", b"hello world", "text/plain"),
])
def test_open_scope_upload_by_any_authenticated_user_is_201(
    fake_storage, user, scope, filename, content, content_type,
):
    if content is None:
        content = _png_bytes()
    resp = _upload(
        Client(), user,
        filename=filename, content=content, content_type=content_type, scope=scope,
    )
    assert resp.status_code == 201


@pytest.mark.django_db
def test_unknown_scope_upload_is_201_falls_back_to_generic_and_logs_warning(
    fake_storage, user, caplog,
):
    with caplog.at_level(logging.WARNING, logger="apps.media_files.services.scope_policy"):
        resp = _upload(
            Client(), user,
            filename="notes.txt", content=b"hello world", content_type="text/plain",
            scope="cms-news",
        )
    assert resp.status_code == 201
    body = resp.json()
    assert body["is_public"] is False  # generic policy behaviour
    assert body["scope"] == "cms-news"  # raw scope string preserved on the row
    assert any(
        "unknown upload scope" in record.getMessage() and "cms-news" in record.getMessage()
        for record in caplog.records
    )


# ─── interface.store_file ────────────────────────────────────────────────────


@pytest.mark.django_db
def test_store_file_restricted_scope_without_authorization_raises(fake_storage):
    with pytest.raises(PermissionDenied):
        interface.store_file(
            data=_pdf_bytes(), filename="handbook.pdf", mime="application/pdf",
            scope="hr_doc", owner_id=1,
        )
    assert not FileMetadata.objects.exists()


@pytest.mark.django_db
def test_store_file_restricted_scope_with_authorization_succeeds(fake_storage):
    result = interface.store_file(
        data=_pdf_bytes(), filename="handbook.pdf", mime="application/pdf",
        scope="hr_doc", owner_id=1, internal_authorized=True,
    )
    assert FileMetadata.objects.filter(id=result["id"]).exists()


@pytest.mark.django_db
def test_store_file_avatar_scope_still_works_unchanged(fake_storage):
    """Regression guard: the current only interface.store_file caller
    (apps.users' avatar path) writes scope="avatar" (open) with no
    internal_authorized kwarg — must be unaffected by this seam."""
    result = interface.store_file(
        data=_png_bytes(), filename="me.png", mime="image/png",
        scope="avatar", owner_id=7,
    )
    assert FileMetadata.objects.filter(id=result["id"], scope="avatar").exists()
