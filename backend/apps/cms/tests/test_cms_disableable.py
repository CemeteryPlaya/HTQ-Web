"""Disableability sweep for the cms domain (Task 1.8, Part A).

Every endpoint currently registered in ``apps/cms/urls.py`` — the
contact-requests family (public POST + admin list/stats/detail/reply/delete,
including both trailing-slash spellings) and ``conference/config`` (both
spellings) — must degrade to the same 503 envelope
(``{"detail": ..., "code": "service_disabled", "service": "cms"}``) the
instant ``ServiceStatus(app_label="cms", enabled=False)``, and it must do so
BEFORE Django even resolves the URL to a view
(``ServiceGateMiddleware``, ``htqweb/middleware/service_gate.py``) — that is
why a disabled cms refuses even its own PUBLIC endpoint, and refuses a
request carrying a perfectly valid admin JWT.

News endpoints (``/api/cms/v1/news/*``) are intentionally NOT swept here:
the news domain's Django port was skipped by the customer (see the Task 1.8
brief), so ``apps/cms/urls.py`` never registers them at all — cms is
therefore not yet functionally complete. When news lands, extend ENDPOINTS
below to match.

Background-task disableability (``require_service("cms")`` inside the
django-q2 actors) is exercised end-to-end, with real task bodies, in
``apps/cms/tests/test_cms_tasks.py``:
``test_translate_news_refuses_when_cms_disabled``,
``test_notify_admins_on_contact_request_refuses_when_cms_disabled``,
``test_publish_scheduled_news_refuses_when_cms_disabled``. This file adds one
tie-together assertion at the bottom
(``test_notify_admins_task_also_refuses_tying_http_and_background_together``)
so the HTTP-gate story and the background-task story are proven from the
same place, against the exact same ``ServiceStatus`` row.
"""

from __future__ import annotations

import json

import jwt as pyjwt
import pytest
from django.conf import settings
from django.test import Client

from apps.core.models import ServiceStatus
from apps.core.services import ServiceDisabled

BASE = "/api/cms/v1"
CONTACT_ID = 1  # the gate intercepts before URL resolution — the row need not exist

# Every (method, path) apps/cms/urls.py registers today. 14 entries = every
# url() line in that file, expanded per HTTP method it actually dispatches.
ENDPOINTS: list[tuple[str, str]] = [
    ("post", f"{BASE}/contact-requests/"),  # public create
    ("get", f"{BASE}/contact-requests/"),  # admin list
    ("get", f"{BASE}/contact-requests/stats"),
    ("get", f"{BASE}/contact-requests/stats/"),
    ("get", f"{BASE}/contact-requests/{CONTACT_ID}"),
    ("get", f"{BASE}/contact-requests/{CONTACT_ID}/"),
    ("patch", f"{BASE}/contact-requests/{CONTACT_ID}"),
    ("patch", f"{BASE}/contact-requests/{CONTACT_ID}/"),
    ("delete", f"{BASE}/contact-requests/{CONTACT_ID}"),
    ("delete", f"{BASE}/contact-requests/{CONTACT_ID}/"),
    ("post", f"{BASE}/contact-requests/{CONTACT_ID}/reply"),
    ("post", f"{BASE}/contact-requests/{CONTACT_ID}/reply/"),
    ("get", f"{BASE}/conference/config"),
    ("get", f"{BASE}/conference/config/"),
]
ENDPOINT_IDS = [f"{m.upper()} {p}" for m, p in ENDPOINTS]


def _disable_cms():
    ServiceStatus.objects.update_or_create(app_label="cms", defaults={"enabled": False})


def _enable_cms():
    ServiceStatus.objects.update_or_create(app_label="cms", defaults={"enabled": True})


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
    assert body["service"] == "cms"
    assert body["detail"]


# ── disabled: every endpoint 503s, with or without a token ──────────────────


@pytest.mark.django_db
@pytest.mark.parametrize("method,path", ENDPOINTS, ids=ENDPOINT_IDS)
def test_endpoint_503_when_disabled_no_token(method, path):
    """No Authorization header at all — proves even the PUBLIC POST refuses."""
    _disable_cms()
    resp = _call(Client(), method, path)
    _assert_disabled_envelope(resp)


@pytest.mark.django_db
@pytest.mark.parametrize("method,path", ENDPOINTS, ids=ENDPOINT_IDS)
def test_endpoint_503_when_disabled_even_with_valid_admin_token(method, path):
    """A perfectly valid admin JWT must NOT let the request past the gate:
    ServiceGateMiddleware runs before Django resolves the URL to a view, so
    auth (and therefore the token's validity) is never even reached."""
    _disable_cms()
    resp = _call(Client(), method, path, **_auth_header(_admin_token()))
    _assert_disabled_envelope(resp)


# ── neighbour stays up ───────────────────────────────────────────────────────


@pytest.mark.django_db
def test_neighbour_health_and_core_services_stay_up_when_cms_disabled():
    _disable_cms()

    health = Client().get("/health/")
    assert health.status_code == 200

    services = Client().get("/api/core/v1/services/")
    assert services.status_code == 200
    assert services.json()["services"]["cms"] is False


# ── enabled (default): guard against a gate that's stuck on ─────────────────


@pytest.mark.django_db
@pytest.mark.parametrize("method,path", ENDPOINTS, ids=ENDPOINT_IDS)
def test_endpoint_does_not_503_when_cms_enabled(method, path):
    _enable_cms()
    resp = _call(Client(), method, path)
    assert resp.status_code != 503


@pytest.mark.django_db
def test_public_post_actually_succeeds_when_cms_enabled():
    """Not just "!= 503" — the public create must actually work end to end,
    closing the loop on the "gate stuck on" guard above."""
    _enable_cms()
    resp = Client().post(
        f"{BASE}/contact-requests/",
        data=json.dumps({
            "first_name": "A", "last_name": "B",
            "email": "gate-check@example.com", "message": "hi",
        }),
        content_type="application/json",
    )
    assert resp.status_code == 201
    assert resp.json()["email"] == "gate-check@example.com"


@pytest.mark.django_db
def test_conference_config_actually_succeeds_when_cms_enabled():
    _enable_cms()
    resp = Client().get(f"{BASE}/conference/config", **_auth_header(_admin_token()))
    assert resp.status_code == 200
    assert "sfu_signaling_url" in resp.json()


@pytest.mark.django_db
def test_admin_list_auth_gates_normally_when_cms_enabled():
    """Without cms's gate in the way, the ADMIN endpoints fall back to their
    normal auth contract (401 with no token) instead of the blanket 503 —
    proves the "!= 503" sweep above isn't passing for some unrelated reason
    (e.g. a crash that also isn't 503)."""
    _enable_cms()
    resp = Client().get(f"{BASE}/contact-requests/")
    assert resp.status_code == 401
    assert "detail" in resp.json()


# ── background side: HTTP gate and require_service() are the same story ────


@pytest.mark.django_db
def test_notify_admins_task_also_refuses_tying_http_and_background_together():
    """Full disableability coverage for cms has two halves: the HTTP gate
    (every parametrized case above) and the ``require_service("cms")`` guard
    inside the django-q2 actors (fully exercised in ``test_cms_tasks.py``).
    This assertion ties them together: the exact same ``ServiceStatus`` row
    that 503s every HTTP endpoint above also makes the task fired from
    ``POST contact-requests/`` (``notify_admins_on_contact_request``)
    refuse — confirming both halves read the same switch.
    """
    from apps.cms.tasks import notify_admins_on_contact_request

    _disable_cms()
    with pytest.raises(ServiceDisabled):
        notify_admins_on_contact_request(1)
