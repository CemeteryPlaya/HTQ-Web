"""StaffingService: CRUD, occupancy, payroll summary."""

import pytest
from datetime import date

from app.models.department import Department
from app.models.position import Position
from app.models.employee import Employee
from app.services.staffing_service import StaffingService

pytestmark = pytest.mark.asyncio


async def _dept_pos(session):
    d = Department(name="Eng", path="eng"); session.add(d); await session.flush()
    p = Position(title="Engineer", department_id=d.id, weight=50); session.add(p); await session.flush()
    return d, p


async def test_create_validates_fk(session):
    svc = StaffingService(session)
    with pytest.raises(Exception):
        await svc.create_line({"position_id": 9999, "department_id": 9999, "headcount": "1", "salary": "100"})


async def test_occupancy_budgeted_filled_vacant(session):
    d, p = await _dept_pos(session)
    svc = StaffingService(session)
    await svc.create_line({"position_id": p.id, "department_id": d.id, "headcount": "2", "salary": "1000"})
    # one active employee on this position+dept
    e = Employee(first_name="A", last_name="B", email="a@b.c",
                 department_id=d.id, position_id=p.id, hire_date=date(2020, 1, 1), status="active")
    session.add(e); await session.commit()
    occ = await svc.occupancy()
    row = next(r for r in occ if r["position_id"] == p.id and r["department_id"] == d.id)
    assert row["budgeted"] == "2.00" and row["filled"] == 1 and row["vacant"] == "1.00"


async def test_multiple_lines_sum_budgeted(session):
    d, p = await _dept_pos(session)
    svc = StaffingService(session)
    await svc.create_line({"position_id": p.id, "department_id": d.id, "headcount": "1.5", "salary": "1000"})
    await svc.create_line({"position_id": p.id, "department_id": d.id, "headcount": "0.5", "salary": "800"})
    occ = await svc.occupancy()
    row = next(r for r in occ if r["position_id"] == p.id)
    assert row["budgeted"] == "2.00" and row["filled"] == 0 and row["vacant"] == "2.00"


async def test_payroll_summary(session):
    d, p = await _dept_pos(session)
    svc = StaffingService(session)
    await svc.create_line({"position_id": p.id, "department_id": d.id, "headcount": "2", "salary": "1000"})
    s = await svc.payroll_summary()
    assert s["total_fot"] == "2000.00"
    dept = next(x for x in s["by_department"] if x["department_id"] == d.id)
    assert dept["fot"] == "2000.00"


async def test_payroll_total_filled_ignores_unrelated_employees(session):
    d, p = await _dept_pos(session)
    svc = StaffingService(session)
    await svc.create_line({"position_id": p.id, "department_id": d.id, "headcount": "2", "salary": "1000"})
    # active employee on a DIFFERENT position+dept (no staffing line) must NOT
    # count toward total_filled / deflate total_vacant.
    d2 = Department(name="Sales", path="sales"); session.add(d2); await session.flush()
    p2 = Position(title="Sales", department_id=d2.id, weight=60); session.add(p2); await session.flush()
    e = Employee(first_name="X", last_name="Y", email="x@y.z",
                 department_id=d2.id, position_id=p2.id, hire_date=date(2020, 1, 1), status="active")
    session.add(e); await session.commit()
    s = await svc.payroll_summary()
    assert s["total_filled"] == 0
    assert s["total_vacant"] == "2.00"
