"""CalendarService: resolution, default switching, working-days, assignment."""

import pytest
from datetime import date

from app.models.department import Department
from app.models.position import Position
from app.models.employee import Employee
from app.models.calendar import WeekTemplate
from app.services.calendar_service import CalendarService

pytestmark = pytest.mark.asyncio

_FIVE_TWO = {str(i): {"type": "working", "hours": 8} for i in range(5)}
_FIVE_TWO.update({"5": {"type": "weekend", "hours": 0}, "6": {"type": "weekend", "hours": 0}})
_SIX_ONE = {str(i): {"type": "working", "hours": 8} for i in range(6)}
_SIX_ONE["6"] = {"type": "weekend", "hours": 0}


async def _default_5_2(session) -> WeekTemplate:
    t = WeekTemplate(name="5/2", is_default=True, days=_FIVE_TWO)
    session.add(t); await session.flush()
    return t


async def _employee(session) -> Employee:
    d = Department(name="D", path="d"); session.add(d); await session.flush()
    p = Position(title="Eng", department_id=d.id, weight=50); session.add(p); await session.flush()
    e = Employee(first_name="A", last_name="B", email="a@b.c",
                 department_id=d.id, position_id=p.id, hire_date=date(2020, 1, 1), status="active")
    session.add(e); await session.flush()
    return e


async def test_default_resolution_weekday_vs_weekend(session):
    await _default_5_2(session)
    svc = CalendarService(session)
    mon = await svc.day_info(date(2026, 6, 1))   # Monday
    sun = await svc.day_info(date(2026, 6, 7))   # Sunday
    assert mon["type"] == "working" and mon["hours"] == 8
    assert sun["type"] == "weekend" and sun["hours"] == 0


async def test_override_wins(session):
    await _default_5_2(session)
    svc = CalendarService(session)
    await svc.upsert_day(date(2026, 6, 1), "holiday", 0, "Holiday")
    info = await svc.day_info(date(2026, 6, 1))
    assert info["type"] == "holiday" and info["hours"] == 0 and info["note"] == "Holiday"


async def test_hard_fallback_without_default(session):
    svc = CalendarService(session)  # no template seeded
    mon = await svc.day_info(date(2026, 6, 1))
    assert mon["type"] == "working" and mon["hours"] == 8


async def test_set_default_moves_flag(session):
    t1 = await _default_5_2(session)
    svc = CalendarService(session)
    t2 = await svc.create_template("6/1", _SIX_ONE, make_default=False)
    await svc.set_default(t2.id)
    await session.refresh(t1); await session.refresh(t2)
    assert t1.is_default is False and t2.is_default is True


async def test_working_days_between_counts_and_sums(session):
    await _default_5_2(session)
    svc = CalendarService(session)
    # 2026-06-01 Mon .. 2026-06-07 Sun → 5 working days * 8h
    res = await svc.working_days_between(date(2026, 6, 1), date(2026, 6, 7))
    assert res["working_days"] == 5 and float(res["norm_hours"]) == 40.0


async def test_employee_uses_assigned_template_else_default(session):
    await _default_5_2(session)
    e = await _employee(session)
    svc = CalendarService(session)
    # unassigned → default 5/2 → Saturday is weekend
    sat = await svc.employee_day_info(e.id, date(2026, 6, 6))
    assert sat["type"] == "weekend"
    # assign 6/1 → Saturday becomes working
    t61 = await svc.create_template("6/1", _SIX_ONE, make_default=False)
    await svc.assign_template(e.id, t61.id)
    sat2 = await svc.employee_day_info(e.id, date(2026, 6, 6))
    assert sat2["type"] == "working" and sat2["hours"] == 8
    # unassign → back to default
    await svc.assign_template(e.id, None)
    sat3 = await svc.employee_day_info(e.id, date(2026, 6, 6))
    assert sat3["type"] == "weekend"
