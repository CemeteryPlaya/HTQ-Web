"""Integration tests for conference config endpoint."""

import pytest

from tests.conftest import user_headers


@pytest.mark.asyncio
async def test_conference_config_authenticated(client, tmp_path):
    """Authenticated user gets conference config."""
    resp = await client.get(
        "/api/cms/v1/conference/config",
        headers=user_headers(),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "sfu_signaling_url" in data
    assert "sfu_signaling_path" in data
    assert "ice_servers" in data


@pytest.mark.asyncio
async def test_conference_config_unauthenticated(client):
    """Unauthenticated request is rejected."""
    resp = await client.get("/api/cms/v1/conference/config")
    assert resp.status_code in (401, 403)
