"""Disableability sweep for the media domain (Task 3.4).

Every endpoint currently registered in ``apps/media_files/urls.py`` — 5
``path()`` lines, expanded per HTTP method each one actually dispatches (two
lines share the ``{file_id}/{tail}`` shape, disambiguated purely by method
inside ``views.file_tail_dispatch``; ``files/`` and its no-slash alias each
dispatch GET/POST inside ``views.files_collection`` — see that module's
comments) — must degrade to the same 503 envelope (``{"detail": ...,
"code": "service_disabled", "service": "media"}``) the instant
``ServiceStatus(app_label="media", enabled=False)``, and it must do so
BEFORE Django even resolves the URL to a view (``ServiceGateMiddleware``,
``htqweb/middleware/service_gate.py``) — that is why a disabled media
refuses even its own PUBLIC read routes (``download_file``,
``download_variant``, ``serve_raw_key`` all have ``auth=None``): a disabled
app must refuse public reads too, not just admin/authenticated writes.

ENDPOINTS below was built by walking ``apps/media_files/urls.py`` line by
line and expanding every method each view actually accepts (same method the
``users``/``cms`` sweeps used to verify their own counts):

  1. files/                                    POST (upload), GET (list)
  2. files (no-slash alias)                    POST, GET
  3. files/<uuid:file_id>/<str:tail>            GET (variant), POST (sign)
  4. files/<uuid:file_id>                       GET (download original)
  5. files/<path:file_key>                      GET (raw storage-key serving)

5 url() lines -> 8 (method, path) combinations below (6 distinct route
*shapes* since #1/#2 are the same dispatcher on two spellings and #3 is one
dispatcher serving two methods — cross-checked against urls.py so nothing
is missed).

Background-task disableability for media's Celery tasks
(``make_variants``/``purge_soft_deleted``/``cleanup_orphan_files``) is
covered separately — see ``test_media_tasks.py`` and (for ``make_variants``)
``test_upload_api.py`` — not duplicated here; this file is HTTP-layer only.
"""

from __future__ import annotations

import json

import jwt as pyjwt
import pytest
from django.conf import settings
from django.test import Client
from django.test.client import BOUNDARY, MULTIPART_CONTENT, encode_multipart

from apps.core.models import ServiceStatus
from apps.core.services import ServiceDisabled

BASE = "/api/media/v1"
FILE_ID = "11111111-1111-1111-1111-111111111111"  # the gate intercepts before URL
                                                    # resolution — the row need not exist
VARIANT = "thumb_32"
RAW_KEY = "avatars/1/x.jpg"  # must contain "/" to hit the serve_raw_key catch-all

# Every (method, path) apps/media_files/urls.py registers today, expanded
# per HTTP method each view actually dispatches. 8 entries covering all 5
# url() lines (see module docstring for the line-by-line mapping).
ENDPOINTS: list[tuple[str, str]] = [
    ("post", f"{BASE}/files/"),
    ("get", f"{BASE}/files/"),
    ("post", f"{BASE}/files"),
    ("get", f"{BASE}/files"),
    ("get", f"{BASE}/files/{FILE_ID}/{VARIANT}"),
    ("post", f"{BASE}/files/{FILE_ID}/sign"),
    ("get", f"{BASE}/files/{FILE_ID}"),
    ("get", f"{BASE}/files/{RAW_KEY}"),
]
ENDPOINT_IDS = [f"{m.upper()} {p}" for m, p in ENDPOINTS]

assert len(ENDPOINTS) == 8


def _disable_media():
    ServiceStatus.objects.update_or_create(app_label="media", defaults={"enabled": False})


def _enable_media():
    ServiceStatus.objects.update_or_create(app_label="media", defaults={"enabled": True})


def _admin_token():
    claims = {
        "user_id": 9, "username": "admin", "email": "admin@htq.test",
        "is_staff": True, "is_superuser": True, "is_admin": True,
        "token_type": "access", "iat": 1, "exp": 9_999_999_999,
        "iss": "htqweb-auth", "sub": "9",
    }
    return pyjwt.encode(claims, settings.JWT_SECRET, algorithm="HS256")


def _auth_header(token: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


# upload_file (POST files/ and its no-slash alias) expects multipart, not
# JSON — everything else that POSTs (sign) is JSON.
_UPLOAD_PATHS = {f"{BASE}/files/", f"{BASE}/files"}


def _call(client: Client, method: str, path: str, **extra):
    fn = getattr(client, method)
    if method != "post":
        return fn(path, **extra)
    if path in _UPLOAD_PATHS:
        # An empty multipart POST is fine — it 422s on the missing 'file'
        # field well past the gate, and we only care that the gate fires
        # first when media is disabled.
        return fn(path, data={}, **extra)
    return fn(path, data=json.dumps({}), content_type="application/json", **extra)


def _assert_disabled_envelope(resp):
    assert resp.status_code == 503
    body = resp.json()
    assert set(body) == {"detail", "code", "service"}
    assert body["code"] == "service_disabled"
    assert body["service"] == "media"
    assert body["detail"]


# ── disabled: every endpoint 503s, with or without a token ──────────────────


@pytest.mark.django_db
@pytest.mark.parametrize("method,path", ENDPOINTS, ids=ENDPOINT_IDS)
def test_endpoint_503_when_disabled_no_token(method, path):
    """No Authorization header at all — proves even the PUBLIC file-serving
    routes (download original/variant, raw-key) refuse too."""
    _disable_media()
    resp = _call(Client(), method, path)
    _assert_disabled_envelope(resp)


@pytest.mark.django_db
@pytest.mark.parametrize("method,path", ENDPOINTS, ids=ENDPOINT_IDS)
def test_endpoint_503_when_disabled_even_with_valid_admin_token(method, path):
    """A perfectly valid admin JWT must NOT let the request past the gate:
    ServiceGateMiddleware runs before Django resolves the URL to a view, so
    auth (and therefore the token's validity) is never even reached."""
    _disable_media()
    resp = _call(Client(), method, path, **_auth_header(_admin_token()))
    _assert_disabled_envelope(resp)


# ── neighbour stays up ───────────────────────────────────────────────────────


@pytest.mark.django_db
def test_neighbour_health_and_core_services_stay_up_when_media_disabled():
    _disable_media()

    health = Client().get("/health/")
    assert health.status_code == 200

    services = Client().get("/api/core/v1/services/")
    assert services.status_code == 200
    assert services.json()["services"]["media"] is False


# ── enabled (default): guard against a gate that's stuck on ─────────────────


@pytest.mark.django_db
@pytest.mark.parametrize("method,path", ENDPOINTS, ids=ENDPOINT_IDS)
def test_endpoint_does_not_503_when_media_enabled(method, path):
    _enable_media()
    resp = _call(Client(), method, path)
    assert resp.status_code != 503


@pytest.mark.django_db
def test_download_original_falls_back_to_normal_404_contract_when_enabled():
    """Not just "!= 503" — without media's gate in the way, an unknown file
    id falls back to its normal contract (404) instead of the blanket 503,
    closing the loop on the "gate stuck on" guard above."""
    _enable_media()
    resp = Client().get(f"{BASE}/files/{FILE_ID}")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_upload_auth_gates_normally_when_media_enabled():
    """Without media's gate in the way, the auth-required upload endpoint
    falls back to its normal auth contract (401) instead of the blanket
    503 — proves the "!= 503" sweep above isn't passing for some unrelated
    reason (e.g. a crash that also isn't 503)."""
    _enable_media()
    resp = Client().post(f"{BASE}/files/", data={})
    assert resp.status_code == 401
    assert "detail" in resp.json()


@pytest.mark.django_db
def test_public_file_actually_served_when_media_enabled(monkeypatch):
    """A concrete end-to-end success case, not just "not 503" — closes the
    loop on the enabled-guard sweep the way cms's
    ``test_public_post_actually_succeeds_when_cms_enabled`` /
    users's ``test_options_endpoint_actually_succeeds_when_users_enabled``
    do."""
    from apps.media_files import views
    from apps.media_files.models import FileMetadata

    _enable_media()

    class _Storage:
        def exists(self, path):
            return True

        def open(self, path, byte_range=None):
            return b"hello"

    monkeypatch.setattr(views, "get_storage", lambda bucket=None: _Storage())

    meta = FileMetadata.objects.create(
        path="p", original_filename="p.txt", size=5, mime="text/plain",
        is_public=True, kind="document", scope="generic",
    )
    resp = Client().get(f"{BASE}/files/{meta.id}")
    assert resp.status_code == 200
    assert resp.content == b"hello"


# ── THE CRITICAL TEST — media being down must not break neighbours ─────────


@pytest.mark.django_db
def test_users_profile_patch_without_avatar_still_works_when_media_disabled():
    """This is the whole reason the platform can afford a ``media``
    kill-switch.

    ``apps.users.views._update_profile`` only reaches into storage (via
    ``apps.users.services.profile_service.save_avatar``) when the request
    actually attaches an ``avatar`` file (decision Р3: writes directly to
    ``htqweb.storage``, no S2S/interface call into ``apps.media_files`` at
    all — see that view's module docstring). A profile PATCH that never
    touches the avatar field must therefore succeed completely normally
    even with ``media`` disabled, proving the domains are genuinely
    decoupled and not just "usually don't collide" — mirrors
    ``apps/users/tests/test_users_disableable.py``'s
    ``test_cms_endpoint_still_works_with_valid_token_when_users_disabled``.
    """
    from apps.users.models import User, UserStatus
    from htqweb.authn.jwt import issue_token_pair

    _disable_media()
    ServiceStatus.objects.update_or_create(app_label="users", defaults={"enabled": True})

    user = User.objects.create(username="nomedia", email="nomedia@htq.test",
                                status=UserStatus.ACTIVE, first_name="No", last_name="Media")
    user.set_password("S3cret!")
    user.save()
    token = issue_token_pair(user)["access"]

    body = encode_multipart(BOUNDARY, {"bio": "media is down, I'm fine"})
    resp = Client().patch(
        "/api/users/v1/profile/me", data=body, content_type=MULTIPART_CONTENT,
        **_auth_header(token),
    )

    assert resp.status_code == 200, (
        f"expected users's profile PATCH (no avatar) to succeed while media "
        f"is disabled; got {resp.status_code}: {resp.content!r}"
    )
    user.refresh_from_db()
    assert user.bio == "media is down, I'm fine"
