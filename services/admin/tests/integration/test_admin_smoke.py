"""Smoke tests for admin-service.

The admin service exposes:
- /health/ liveness
- /sqladmin/ (login + dashboard, requires admin_session cookie)

These tests verify the surface is wired without exercising sqladmin's full
ModelView flow (that needs real DB rows + browser session).
"""

import pytest
import jwt
from datetime import datetime, timedelta, timezone

from app.core.settings import settings


def make_admin_token() -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "user_id": 1,
        "username": "admin",
        "email": "admin@test.local",
        "is_staff": True,
        "is_superuser": False,
        "is_admin": True,
        "token_type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=30),
        "iss": settings.jwt_issuer,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


@pytest.mark.asyncio
async def test_health(client):
    resp = await client.get("/health/")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_sqladmin_login_page_renders(client):
    resp = await client.get("/sqladmin/login")
    # sqladmin login page is HTML (200) — anonymous can fetch the form
    assert resp.status_code == 200
    assert "html" in resp.headers.get("content-type", "").lower()


@pytest.mark.asyncio
async def test_sqladmin_dashboard_redirects_anon(client):
    """Anonymous request to /sqladmin/ should redirect to login."""
    resp = await client.get("/sqladmin/", follow_redirects=False)
    # sqladmin returns 302/303 to /sqladmin/login (or 401 depending on backend)
    assert resp.status_code in (302, 303, 401)


@pytest.mark.asyncio
async def test_infrastructure_requires_admin(client):
    resp = await client.get("/api/admin/v1/infrastructure/")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_infrastructure_masks_credentials(client):
    resp = await client.get(
        "/api/admin/v1/infrastructure/",
        headers={"Authorization": f"Bearer {make_admin_token()}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["credentials_visible"] is False
    postgres = next(resource for resource in body["resources"] if resource["id"] == "postgres")
    password = next(field for field in postgres["credentials"] if field["key"] == "password")
    assert password["masked"] is True
    assert password["copyable"] is False


@pytest.mark.asyncio
async def test_infrastructure_health_requires_admin(client):
    resp = await client.get("/api/admin/v1/infrastructure/health-check")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_infrastructure_health_returns_results(client, monkeypatch):
    async def fake_postgres():
        return "ok", "fake"

    async def fake_redis():
        return "ok", "fake"

    async def fake_mongo():
        return "ok", "fake"

    async def fake_minio():
        raise RuntimeError("boom")

    monkeypatch.setattr("app.api.v1.infrastructure._check_postgres", fake_postgres)
    monkeypatch.setattr("app.api.v1.infrastructure._check_redis", fake_redis)
    monkeypatch.setattr("app.api.v1.infrastructure._check_mongo", fake_mongo)
    monkeypatch.setattr("app.api.v1.infrastructure._check_minio", fake_minio)
    monkeypatch.setitem(
        __import__("app.api.v1.infrastructure", fromlist=["_HEALTH_CHECKS"])._HEALTH_CHECKS,
        "postgres", fake_postgres,
    )
    monkeypatch.setitem(
        __import__("app.api.v1.infrastructure", fromlist=["_HEALTH_CHECKS"])._HEALTH_CHECKS,
        "redis", fake_redis,
    )
    monkeypatch.setitem(
        __import__("app.api.v1.infrastructure", fromlist=["_HEALTH_CHECKS"])._HEALTH_CHECKS,
        "mongo", fake_mongo,
    )
    monkeypatch.setitem(
        __import__("app.api.v1.infrastructure", fromlist=["_HEALTH_CHECKS"])._HEALTH_CHECKS,
        "minio", fake_minio,
    )

    resp = await client.get(
        "/api/admin/v1/infrastructure/health-check",
        headers={"Authorization": f"Bearer {make_admin_token()}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    by_id = {r["id"]: r for r in body["results"]}
    assert by_id["postgres"]["status"] == "ok"
    assert by_id["minio"]["status"] == "error"
    assert "boom" in by_id["minio"]["message"]


@pytest.mark.asyncio
async def test_infrastructure_reveal_requires_reauth(client, monkeypatch):
    async def reauth_ok(_payload, _password):
        return None

    monkeypatch.setattr("app.api.v1.infrastructure._reauthenticate_admin", reauth_ok)

    resp = await client.post(
        "/api/admin/v1/infrastructure/credentials/reveal",
        headers={"Authorization": f"Bearer {make_admin_token()}"},
        json={"password": "admin-password"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["credentials_visible"] is True
    postgres = next(resource for resource in body["resources"] if resource["id"] == "postgres")
    password = next(field for field in postgres["credentials"] if field["key"] == "password")
    assert password["masked"] is False
    assert password["copyable"] is True
