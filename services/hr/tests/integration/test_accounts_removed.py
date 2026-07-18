"""The hr-service accounts proxy is removed; its routes must 404."""

import pytest
from tests.conftest import admin_headers

pytestmark = pytest.mark.asyncio


async def test_accounts_list_route_gone(client):
    resp = await client.get("/api/hr/v1/accounts/", headers=admin_headers())
    assert resp.status_code == 404
