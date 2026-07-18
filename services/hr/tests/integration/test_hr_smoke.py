"""Smoke tests for hr-service routing + auth + DB wiring."""

import pytest
from tests.conftest import admin_headers


@pytest.mark.asyncio
async def test_employees_list_requires_auth(client):
    resp = await client.get("/api/hr/v1/employees/")
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_employees_list_admin_returns_envelope(client):
    resp = await client.get("/api/hr/v1/employees/", headers=admin_headers())
    assert resp.status_code == 200
    body = resp.json()
    # Either bare list or paginated envelope {items: [...], total: N}
    if isinstance(body, dict):
        assert "items" in body
        assert isinstance(body["items"], list)
    else:
        assert isinstance(body, list)


@pytest.mark.asyncio
async def test_departments_list_admin(client):
    resp = await client.get("/api/hr/v1/departments/", headers=admin_headers())
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_positions_list_admin(client):
    resp = await client.get("/api/hr/v1/positions/", headers=admin_headers())
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_personnel_history_admin(client):
    resp = await client.get("/api/hr/v1/personnel-history/", headers=admin_headers())
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_audit_logs_admin(client):
    resp = await client.get("/api/hr/v1/logs/", headers=admin_headers())
    assert resp.status_code == 200
