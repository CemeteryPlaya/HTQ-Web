"""Calendar endpoints honor view/manage keys (admin token → wildcard)."""

import pytest
from datetime import date

from app.models.calendar import WeekTemplate
from tests.conftest import admin_headers

pytestmark = pytest.mark.asyncio

_FIVE_TWO = {str(i): {"type": "working", "hours": 8} for i in range(5)}
_FIVE_TWO.update({"5": {"type": "weekend", "hours": 0}, "6": {"type": "weekend", "hours": 0}})


async def _seed_default(session):
    session.add(WeekTemplate(name="5/2", is_default=True, days=_FIVE_TWO))
    await session.commit()


async def test_working_days_endpoint(client, session):
    await _seed_default(session)
    r = await client.get("/api/hr/v1/calendar/working-days",
                         params={"start": "2026-06-01", "end": "2026-06-07"},
                         headers=admin_headers())
    assert r.status_code == 200, r.text
    assert r.json()["working_days"] == 5


async def test_put_override_then_year_reflects_it(client, session):
    await _seed_default(session)
    p = await client.put("/api/hr/v1/calendar/2026-06-01",
                         json={"day_type": "holiday", "norm_hours": 0, "note": "X"},
                         headers=admin_headers())
    assert p.status_code == 200, p.text
    y = await client.get("/api/hr/v1/calendar/", params={"year": 2026}, headers=admin_headers())
    assert y.status_code == 200
    jun1 = next(d for d in y.json() if d["day"] == "2026-06-01")
    assert jun1["type"] == "holiday"


from app.models.department import Department
from app.models.position import Position
from app.models.employee import Employee


async def _seed_employee(session):
    d = Department(name="D", path="d"); session.add(d); await session.flush()
    p = Position(title="Eng", department_id=d.id, weight=50); session.add(p); await session.flush()
    e = Employee(first_name="A", last_name="B", email="emp@b.c",
                 department_id=d.id, position_id=p.id, hire_date=date(2020, 1, 1), status="active")
    session.add(e); await session.flush(); await session.commit()
    return e.id


async def test_assign_template_then_employee_calendar(client, session):
    await _seed_default(session)
    emp_id = await _seed_employee(session)
    # create a 6/1 template
    six_one = {str(i): {"type": "working", "hours": 8} for i in range(6)}
    six_one["6"] = {"type": "weekend", "hours": 0}
    c = await client.post("/api/hr/v1/calendar/templates",
                          json={"name": "6/1", "days": six_one}, headers=admin_headers())
    assert c.status_code == 201, c.text
    tid = c.json()["id"]
    a = await client.put(f"/api/hr/v1/employees/{emp_id}/calendar-template",
                         json={"week_template_id": tid}, headers=admin_headers())
    assert a.status_code == 200, a.text
    g = await client.get(f"/api/hr/v1/employees/{emp_id}/calendar",
                         params={"start": "2026-06-06", "end": "2026-06-06"}, headers=admin_headers())
    assert g.status_code == 200
    assert g.json()[0]["type"] == "working"  # Saturday is working under 6/1
