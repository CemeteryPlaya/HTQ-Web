"""Disableability sweep for the users domain (Task 2.7, Part A).

Every endpoint currently registered in ``apps/users/urls.py`` — 24 url()
lines, expanded per HTTP method each one actually dispatches (some paths are
GET/PATCH or GET/POST/PATCH/DELETE collection-or-detail dispatchers that
route by ``request.method`` inside a single view, see that module's
comments) — must degrade to the same 503 envelope (``{"detail": ...,
"code": "service_disabled", "service": "users"}``) the instant
``ServiceStatus(app_label="users", enabled=False)``, and it must do so
BEFORE Django even resolves the URL to a view (``ServiceGateMiddleware``,
``htqweb/middleware/service_gate.py``) — that is why a disabled users
refuses even its own PUBLIC endpoints (``token/``, ``register/``,
``client-errors``, ``client-events``) and a request carrying a perfectly
valid admin JWT.

ENDPOINTS below was built by walking ``apps/users/urls.py`` line by line and
expanding every method each view actually accepts:

  1. token/                                          POST
  2. token/refresh/                                  POST
  3. admin-session/login                             POST
  4. admin-session/logout                             POST
  5. profile/me                                       GET, PATCH
  6. profile/                                          GET, PATCH
  7. profile/change-password (+ /)                    POST x2
  8. profile/avatar (+ /)                              DELETE x2
  9. register/                                         POST
 10. pending-registrations/                            GET
 11. pending-registrations/<id>/approve/               POST
 12. pending-registrations/<id>/reject/                POST
 13. admin/users/                                       GET, POST
 14. admin/users/<id>/set-password/                     POST
 15. admin/users/<id>/                                  PATCH, DELETE
 16. items/                                             GET, POST
 17. items/<id>/                                        GET, PATCH, DELETE
 18. client-errors (+ /)                                POST x2
 19. client-events (+ /)                                POST x2
 20. users/options/                                     GET

24 url() lines -> 31 (method, path) combinations below (cross-checked
against urls.py so nothing is missed, same method the cms review used to
verify 14/14).

Background-task disableability doesn't apply here — unlike cms, the users
app has no Celery/Dramatiq task bodies of its own to sweep (see
``apps.users.services.registration_service``/``admin_service`` module
docstrings: decision Р2 dropped the Redis pub/sub broadcasts, so there's no
background code path left that calls ``require_service("users")``).
"""

from __future__ import annotations

import json

import jwt as pyjwt
import pytest
from django.conf import settings
from django.test import Client

from apps.core.models import ServiceStatus
from apps.core.services import ServiceDisabled

BASE = "/api/users/v1"
USER_ID = 1  # the gate intercepts before URL resolution — the row need not exist
ITEM_ID = 1

# Every (method, path) apps/users/urls.py registers today, expanded per
# HTTP method each view actually dispatches. 31 entries covering all 24
# url() lines (see module docstring for the line-by-line mapping).
ENDPOINTS: list[tuple[str, str]] = [
    ("post", f"{BASE}/token/"),
    ("post", f"{BASE}/token/refresh/"),
    ("post", f"{BASE}/admin-session/login"),
    ("post", f"{BASE}/admin-session/logout"),
    ("get", f"{BASE}/profile/me"),
    ("patch", f"{BASE}/profile/me"),
    ("get", f"{BASE}/profile/"),
    ("patch", f"{BASE}/profile/"),
    ("post", f"{BASE}/profile/change-password"),
    ("post", f"{BASE}/profile/change-password/"),
    ("delete", f"{BASE}/profile/avatar"),
    ("delete", f"{BASE}/profile/avatar/"),
    ("post", f"{BASE}/register/"),
    ("get", f"{BASE}/pending-registrations/"),
    ("post", f"{BASE}/pending-registrations/{USER_ID}/approve/"),
    ("post", f"{BASE}/pending-registrations/{USER_ID}/reject/"),
    ("get", f"{BASE}/admin/users/"),
    ("post", f"{BASE}/admin/users/"),
    ("post", f"{BASE}/admin/users/{USER_ID}/set-password/"),
    ("patch", f"{BASE}/admin/users/{USER_ID}/"),
    ("delete", f"{BASE}/admin/users/{USER_ID}/"),
    ("get", f"{BASE}/items/"),
    ("post", f"{BASE}/items/"),
    ("get", f"{BASE}/items/{ITEM_ID}/"),
    ("patch", f"{BASE}/items/{ITEM_ID}/"),
    ("delete", f"{BASE}/items/{ITEM_ID}/"),
    ("post", f"{BASE}/client-errors"),
    ("post", f"{BASE}/client-errors/"),
    ("post", f"{BASE}/client-events"),
    ("post", f"{BASE}/client-events/"),
    ("get", f"{BASE}/users/options/"),
]
ENDPOINT_IDS = [f"{m.upper()} {p}" for m, p in ENDPOINTS]

assert len(ENDPOINTS) == 31


def _disable_users():
    ServiceStatus.objects.update_or_create(app_label="users", defaults={"enabled": False})


def _enable_users():
    ServiceStatus.objects.update_or_create(app_label="users", defaults={"enabled": True})


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


def _call(client: Client, method: str, path: str, **extra):
    fn = getattr(client, method)
    if method in ("post", "patch"):
        return fn(path, data=json.dumps({}), content_type="application/json", **extra)
    return fn(path, **extra)


def _assert_disabled_envelope(resp):
    assert resp.status_code == 503
    body = resp.json()
    assert set(body) == {"detail", "code", "service"}
    assert body["code"] == "service_disabled"
    assert body["service"] == "users"
    assert body["detail"]


# ── disabled: every endpoint 503s, with or without a token ──────────────────


@pytest.mark.django_db
@pytest.mark.parametrize("method,path", ENDPOINTS, ids=ENDPOINT_IDS)
def test_endpoint_503_when_disabled_no_token(method, path):
    """No Authorization header at all — proves even the PUBLIC endpoints
    (token/, register/, client-errors, client-events) refuse too."""
    _disable_users()
    resp = _call(Client(), method, path)
    _assert_disabled_envelope(resp)


@pytest.mark.django_db
@pytest.mark.parametrize("method,path", ENDPOINTS, ids=ENDPOINT_IDS)
def test_endpoint_503_when_disabled_even_with_valid_admin_token(method, path):
    """A perfectly valid admin JWT must NOT let the request past the gate:
    ServiceGateMiddleware runs before Django resolves the URL to a view, so
    auth (and therefore the token's validity) is never even reached."""
    _disable_users()
    resp = _call(Client(), method, path, **_auth_header(_admin_token()))
    _assert_disabled_envelope(resp)


# ── neighbour stays up ───────────────────────────────────────────────────────


@pytest.mark.django_db
def test_neighbour_health_and_core_services_stay_up_when_users_disabled():
    _disable_users()

    health = Client().get("/health/")
    assert health.status_code == 200

    services = Client().get("/api/core/v1/services/")
    assert services.status_code == 200
    assert services.json()["services"]["users"] is False


# ── enabled (default): guard against a gate that's stuck on ─────────────────


@pytest.mark.django_db
@pytest.mark.parametrize("method,path", ENDPOINTS, ids=ENDPOINT_IDS)
def test_endpoint_does_not_503_when_users_enabled(method, path):
    _enable_users()
    resp = _call(Client(), method, path)
    assert resp.status_code != 503


@pytest.mark.django_db
def test_public_token_endpoint_falls_back_to_normal_auth_contract_when_enabled():
    """Not just "!= 503" — without users's gate in the way, token/ falls
    back to its normal contract (401 invalid credentials) instead of the
    blanket 503, closing the loop on the "gate stuck on" guard above."""
    _enable_users()
    resp = Client().post(
        f"{BASE}/token/",
        data=json.dumps({"email": "nobody@example.com", "password": "wrong"}),
        content_type="application/json",
    )
    assert resp.status_code == 401


@pytest.mark.django_db
def test_admin_list_auth_gates_normally_when_users_enabled():
    """Without users's gate in the way, the ADMIN endpoints fall back to
    their normal auth contract (401 with no token) instead of the blanket
    503 — proves the "!= 503" sweep above isn't passing for some unrelated
    reason (e.g. a crash that also isn't 503)."""
    _enable_users()
    resp = Client().get(f"{BASE}/admin/users/")
    assert resp.status_code == 401
    assert "detail" in resp.json()


@pytest.mark.django_db
def test_options_endpoint_actually_succeeds_when_users_enabled():
    """A concrete end-to-end success case, not just "not 503" — closes the
    loop on the enabled-guard sweep the way cms's
    ``test_public_post_actually_succeeds_when_cms_enabled`` does."""
    from apps.users.models import User, UserStatus
    from htqweb.authn.jwt import issue_token_pair

    _enable_users()
    user = User.objects.create(username="sweep", email="sweep@htq.test",
                                status=UserStatus.ACTIVE, first_name="Sweep", last_name="Er")
    user.set_password("S3cret!")
    user.save()
    token = issue_token_pair(user)["access"]
    resp = Client().get(f"{BASE}/users/options/", **_auth_header(token))
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


# ── THE CRITICAL TEST — token validation must survive users being off ──────


@pytest.mark.django_db
def test_cms_endpoint_still_works_with_valid_token_when_users_disabled():
    """This is the whole reason the platform can afford a ``users``
    kill-switch.

    JWT validation (``htqweb.authn.jwt.decode_token``, used by
    ``htqweb.http.api_view(auth="jwt")``) is LOCAL: it verifies the token's
    signature/issuer/exp entirely offline against ``settings.JWT_SECRET`` —
    it never queries the ``users`` app's models, services, or interface, and
    never makes an S2S call to anything. So flipping ``users`` off must NOT
    log out the rest of the platform: any other app's ``auth="jwt"``
    endpoint must keep accepting a token that was valid before the flip.

    Proven here against ``GET /api/cms/v1/conference/config``
    (``apps/cms/views.py::conference_config``, ``auth="jwt"``, no admin gate
    beyond "a valid token") with ``users`` disabled and ``cms`` explicitly
    enabled. If this test fails, the kill-switch is unusable — disabling
    `users` for maintenance would accidentally lock every user in the
    platform out of every OTHER app too, defeating the entire point of
    per-app disableability (see the Phase 2 master plan, risk Р4/isolation).
    This would be a Critical finding.
    """
    _disable_users()
    ServiceStatus.objects.update_or_create(app_label="cms", defaults={"enabled": True})

    resp = Client().get("/api/cms/v1/conference/config", **_auth_header(_admin_token()))

    assert resp.status_code == 200, (
        f"expected cms to still accept a valid token while users is "
        f"disabled; got {resp.status_code}: {resp.content!r}"
    )
    assert "sfu_signaling_url" in resp.json()
