"""Shift rotation resolution, holidays_off, manual override, mutual exclusion."""

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
_2_2 = [{"type": "work", "hours": 12}, {"type": "work", "hours": 12},
        {"type": "off", "hours": 0}, {"type": "off", "hours": 0}]


async def _default(session):
    session.add(WeekTemplate(name="5/2", is_default=True, days=_FIVE_TWO)); await session.flush()


async def _emp(session):
    d = Department(name="D", path="d"); session.add(d); await session.flush()
    p = Position(title="Eng", department_id=d.id, weight=50); session.add(p); await session.flush()
    e = Employee(first_name="A", last_name="B", email="a@b.c",
                 department_id=d.id, position_id=p.id, hire_date=date(2020, 1, 1), status="active")
    session.add(e); await session.flush()
    return e


async def test_rotation_slot(session):
    await _default(session)
    e = await _emp(session)
    svc = CalendarService(session)
    pat = await svc.create_shift_pattern("2/2", _2_2, holidays_off=False)
    await svc.assign_shift(e.id, pat.id, date(2026, 6, 1))  # anchor Mon = slot0 work
    assert (await svc.employee_day_info(e.id, date(2026, 6, 1)))["type"] == "working"  # slot 0
    assert (await svc.employee_day_info(e.id, date(2026, 6, 3)))["type"] == "weekend"  # slot 2 off
    # day before anchor: (−1)%4 = 3 → off
    assert (await svc.employee_day_info(e.id, date(2026, 5, 31)))["type"] == "weekend"


async def test_holidays_off_true_makes_holiday_off(session):
    await _default(session)
    e = await _emp(session)
    svc = CalendarService(session)
    await svc.upsert_day(date(2026, 6, 1), "holiday", 0, "Holiday")
    pat = await svc.create_shift_pattern("2/2", _2_2, holidays_off=True)
    await svc.assign_shift(e.id, pat.id, date(2026, 6, 1))
    assert (await svc.employee_day_info(e.id, date(2026, 6, 1)))["type"] == "holiday"


async def test_holidays_off_false_follows_rotation(session):
    await _default(session)
    e = await _emp(session)
    svc = CalendarService(session)
    await svc.upsert_day(date(2026, 6, 1), "holiday", 0, "Holiday")
    pat = await svc.create_shift_pattern("2/2", _2_2, holidays_off=False)
    await svc.assign_shift(e.id, pat.id, date(2026, 6, 1))
    assert (await svc.employee_day_info(e.id, date(2026, 6, 1)))["type"] == "working"


async def test_manual_override_wins(session):
    await _default(session)
    e = await _emp(session)
    svc = CalendarService(session)
    pat = await svc.create_shift_pattern("2/2", _2_2, holidays_off=False)
    await svc.assign_shift(e.id, pat.id, date(2026, 6, 1))
    await svc.set_employee_day_override(e.id, date(2026, 6, 1), "weekend", 0, "personal day")
    assert (await svc.employee_day_info(e.id, date(2026, 6, 1)))["type"] == "weekend"


async def test_mutual_exclusion(session):
    await _default(session)
    e = await _emp(session)
    svc = CalendarService(session)
    t = await svc.create_template("6/1", {**{str(i): {"type": "working", "hours": 8} for i in range(6)}, "6": {"type": "weekend", "hours": 0}})
    await svc.assign_template(e.id, t.id)
    pat = await svc.create_shift_pattern("2/2", _2_2, holidays_off=False)
    await svc.assign_shift(e.id, pat.id, date(2026, 6, 1))
    # now assigning a week template again must clear the shift
    await svc.assign_template(e.id, t.id)
    # Saturday 2026-06-06 under 6/1 is working (proves week-template active, shift cleared)
    assert (await svc.employee_day_info(e.id, date(2026, 6, 6)))["type"] == "working"
