"""Shift-pattern + employee shift/override endpoints (admin token → wildcard)."""

import pytest
from datetime import date

from app.models.calendar import WeekTemplate
from app.models.department import Department
from app.models.position import Position
from app.models.employee import Employee
from tests.conftest import admin_headers

pytestmark = pytest.mark.asyncio

_FIVE_TWO = {str(i): {"type": "working", "hours": 8} for i in range(5)}
_FIVE_TWO.update({"5": {"type": "weekend", "hours": 0}, "6": {"type": "weekend", "hours": 0}})


async def _seed(session):
    session.add(WeekTemplate(name="5/2", is_default=True, days=_FIVE_TWO))
    d = Department(name="D", path="d"); session.add(d); await session.flush()
    p = Position(title="Eng", department_id=d.id, weight=50); session.add(p); await session.flush()
    e = Employee(first_name="A", last_name="B", email="s@b.c",
                 department_id=d.id, position_id=p.id, hire_date=date(2020, 1, 1), status="active")
    session.add(e); await session.flush(); await session.commit()
    return e.id


async def test_create_pattern_assign_shift_and_resolve(client, session):
    emp_id = await _seed(session)
    c = await client.post("/api/hr/v1/calendar/shift-patterns",
                          json={"name": "2/2", "holidays_off": False,
                                "slots": [{"type": "work", "hours": 12}, {"type": "work", "hours": 12},
                                          {"type": "off", "hours": 0}, {"type": "off", "hours": 0}]},
                          headers=admin_headers())
    assert c.status_code == 201, c.text
    pid = c.json()["id"]
    a = await client.put(f"/api/hr/v1/employees/{emp_id}/shift",
                         json={"shift_pattern_id": pid, "anchor_date": "2026-06-01"}, headers=admin_headers())
    assert a.status_code == 200, a.text
    g = await client.get(f"/api/hr/v1/employees/{emp_id}/calendar",
                         params={"start": "2026-06-03", "end": "2026-06-03"}, headers=admin_headers())
    assert g.status_code == 200
    assert g.json()[0]["type"] == "weekend"  # slot 2 = off


async def test_manual_override_endpoint(client, session):
    emp_id = await _seed(session)
    p = await client.put(f"/api/hr/v1/employees/{emp_id}/calendar/2026-06-01",
                         json={"day_type": "working", "norm_hours": 8, "note": "works holiday"},
                         headers=admin_headers())
    assert p.status_code == 200, p.text
    g = await client.get(f"/api/hr/v1/employees/{emp_id}/calendar",
                         params={"start": "2026-06-01", "end": "2026-06-01"}, headers=admin_headers())
    assert g.json()[0]["type"] == "working"
