"""Contract tests for ``GET /api/cms/v1/conference/config``.

Ports ``services/cms/app/api/v1/conference.py`` (FastAPI cms-service): no
database reads, static WebRTC/SFU runtime config assembled from Django
settings and normalised against the request host. The one addition beyond
the port (Task 1.5) is ``enabled``, sourced from
``apps.core.services.service_enabled("conference")`` — the SFU stack is
seeded DISABLED by the ``apps.core`` seed migration, so the frontend can
learn that from the same config fetch it already makes for
``ConferencePage.tsx``.
"""

import jwt as pyjwt
import pytest
from django.conf import settings
from django.test import Client

from apps.core.models import ServiceStatus

BASE = "/api/cms/v1/conference/config"


def _token(**over):
    claims = {
        "user_id": 7, "username": "u", "email": "u@htq.test",
        "is_staff": False, "is_superuser": False, "is_admin": False,
        "token_type": "access", "iat": 1, "exp": 9_999_999_999,
        "iss": "htqweb-auth", "sub": "7",
        **over,
    }
    return pyjwt.encode(claims, settings.JWT_SECRET, algorithm="HS256")


def _auth_header(token: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


# ── shape: matches the FastAPI ConferenceConfig field-for-field ─────────────

@pytest.mark.django_db
def test_config_returns_200_with_fastapi_original_fields():
    resp = Client().get(BASE, **_auth_header(_token()))
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body["sfu_signaling_url"], str)
    assert isinstance(body["sfu_signaling_path"], str)
    assert isinstance(body["ice_servers"], list)


@pytest.mark.django_db
def test_ice_servers_shape_matches_ice_server_schema():
    resp = Client().get(BASE, **_auth_header(_token()))
    assert resp.status_code == 200
    servers = resp.json()["ice_servers"]
    assert servers  # settings ship two STUN defaults, mirroring conference.yaml
    for server in servers:
        assert isinstance(server["urls"], (str, list))
        assert "username" in server
        assert "credential" in server


@pytest.mark.django_db
def test_sfu_signaling_path_defaults_to_ws_sfu():
    resp = Client().get(BASE, **_auth_header(_token()))
    assert resp.status_code == 200
    assert resp.json()["sfu_signaling_path"] == "/ws/sfu/"


# ── auth: unauthenticated is rejected (mirrors get_current_user dependency) ──

@pytest.mark.django_db
def test_without_token_401():
    resp = Client().get(BASE)
    assert resp.status_code == 401
    assert "detail" in resp.json()


# ── enabled flag: the one intentional addition beyond the port ──────────────

@pytest.mark.django_db
def test_enabled_false_when_conference_disabled_seeded_default():
    ServiceStatus.objects.update_or_create(app_label="conference", defaults={"enabled": False})
    resp = Client().get(BASE, **_auth_header(_token()))
    assert resp.status_code == 200
    assert resp.json()["enabled"] is False


@pytest.mark.django_db
def test_enabled_true_when_conference_enabled():
    ServiceStatus.objects.update_or_create(app_label="conference", defaults={"enabled": True})
    resp = Client().get(BASE, **_auth_header(_token()))
    assert resp.status_code == 200
    assert resp.json()["enabled"] is True


# ── route spelling: both the trailing- and non-trailing-slash calls the ─────
# frontend actually sends (frontend/src/api/cms.ts's apiPath('cms',
# 'conference/config') and ConferencePage.tsx's literal
# 'cms/v1/conference/config' both omit the trailing slash — but
# APPEND_SLASH=False means Django won't redirect a stray trailing slash
# either, so both spellings are registered defensively, matching Task 1.4's
# convention for this app).

@pytest.mark.django_db
def test_no_trailing_slash_resolves():
    resp = Client().get("/api/cms/v1/conference/config", **_auth_header(_token()))
    assert resp.status_code == 200


@pytest.mark.django_db
def test_trailing_slash_resolves():
    resp = Client().get("/api/cms/v1/conference/config/", **_auth_header(_token()))
    assert resp.status_code == 200
