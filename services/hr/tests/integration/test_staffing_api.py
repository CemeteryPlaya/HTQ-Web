"""Staffing endpoints honor view/manage keys (admin token → wildcard)."""

import pytest

from app.models.department import Department
from app.models.position import Position
from tests.conftest import admin_headers

pytestmark = pytest.mark.asyncio


async def _dept_pos(session):
    d = Department(name="Eng", path="eng"); session.add(d); await session.flush()
    p = Position(title="Engineer", department_id=d.id, weight=50); session.add(p)
    await session.commit()
    return d.id, p.id


async def test_create_list_and_summary(client, session):
    did, pid = await _dept_pos(session)
    c = await client.post("/api/hr/v1/staffing/",
                          json={"position_id": pid, "department_id": did, "headcount": "2", "salary": "1000"},
                          headers=admin_headers())
    assert c.status_code == 201, c.text
    assert c.json()["fot"] == "2000.00"
    lst = await client.get("/api/hr/v1/staffing/", headers=admin_headers())
    assert lst.status_code == 200 and len(lst.json()) == 1
    s = await client.get("/api/hr/v1/staffing/summary", headers=admin_headers())
    assert s.status_code == 200 and s.json()["total_fot"] == "2000.00"
