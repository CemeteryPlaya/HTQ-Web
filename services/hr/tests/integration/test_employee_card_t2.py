"""EmployeeCard T2 service: upsert + section-gated read."""

import pytest
from datetime import date

from app.models.department import Department
from app.models.position import Position
from app.models.employee import Employee
from app.auth.hr_access import HRAccess
from app.auth.permissions import LEVEL_PRESETS
from app.services.employee_card_t2_service import EmployeeCardT2Service

pytestmark = pytest.mark.asyncio


async def _employee(session):
    d = Department(name="D", path="d"); session.add(d); await session.flush()
    p = Position(title="Eng", department_id=d.id, weight=50); session.add(p); await session.flush()
    e = Employee(first_name="A", last_name="B", email="a@b.c",
                 department_id=d.id, position_id=p.id, hire_date=date(2020, 1, 1), status="active")
    session.add(e); await session.flush()
    return e


def _acc(level):
    return HRAccess(level=level, permissions=LEVEL_PRESETS[level])


async def test_upsert_creates_then_updates(session):
    e = await _employee(session)
    svc = EmployeeCardT2Service(session)
    await svc.upsert(e.id, {"financial": {"salary": "1000.50", "bonus": "200"}}, _acc("lead"))
    card = await svc.read_sections(e.id, _acc("lead"))
    assert card["financial"]["salary"] == "1000.50"
    await svc.upsert(e.id, {"financial": {"salary": "1500"}}, _acc("lead"))
    card = await svc.read_sections(e.id, _acc("lead"))
    assert card["financial"]["salary"] == "1500.00"


async def test_read_hides_section_without_view_key(session):
    e = await _employee(session)
    svc = EmployeeCardT2Service(session)
    await svc.upsert(e.id, {"financial": {"salary": "999"}, "certs": {"sro_permit_number": "X1"}}, _acc("lead"))
    card = await svc.read_sections(e.id, _acc("middle"))
    assert "financial" not in card
    assert card["certs"]["sro_permit_number"] == "X1"


async def test_upsert_rejects_section_without_edit_key(session):
    e = await _employee(session)
    svc = EmployeeCardT2Service(session)
    with pytest.raises(PermissionError):
        await svc.upsert(e.id, {"financial": {"salary": "1"}}, _acc("middle"))
