"""Т-2 card endpoints honor per-section keys (admin token → all keys)."""

import pytest
from datetime import date

from app.models.department import Department
from app.models.position import Position
from app.models.employee import Employee
from tests.conftest import admin_headers

pytestmark = pytest.mark.asyncio


async def _seed(session):
    d = Department(name="D", path="d"); session.add(d); await session.flush()
    p = Position(title="Eng", department_id=d.id, weight=50); session.add(p); await session.flush()
    e = Employee(first_name="A", last_name="B", email="a@b.c",
                 department_id=d.id, position_id=p.id, hire_date=date(2020, 1, 1), status="active")
    session.add(e); await session.flush(); await session.commit()
    return e.id


async def test_patch_then_get_card_t2_as_admin(client, session):
    emp_id = await _seed(session)
    r = await client.patch(f"/api/hr/v1/employees/{emp_id}/card/t2",
                           json={"financial": {"salary": "1234.50"}}, headers=admin_headers())
    assert r.status_code == 200, r.text
    g = await client.get(f"/api/hr/v1/employees/{emp_id}/card/t2", headers=admin_headers())
    assert g.status_code == 200
    assert g.json()["financial"]["salary"] == "1234.50"


async def test_groups_get_as_admin_returns_lists(client, session):
    emp_id = await _seed(session)
    g = await client.get(f"/api/hr/v1/employees/{emp_id}/card/groups", headers=admin_headers())
    assert g.status_code == 200
    assert set(g.json().keys()) == {"education", "experience", "relatives"}
