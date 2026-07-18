"""Integration tests for PMO allocation, primary member, and reverse lookup."""

from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.models.department import Department
from app.models.employee import Employee
from app.models.level_threshold import LevelThreshold
from app.models.pmo import PMO, PMOMember
from app.models.position import Position
from tests.conftest import admin_headers


pytestmark = pytest.mark.asyncio


async def _seed_people(session, count: int = 3) -> list[Employee]:
    session.add(LevelThreshold(level_number=1, weight_from=0, weight_to=9999, label="All", color="#3b82f6"))
    dept = Department(name="Delivery", path="company.delivery", unit_type="department")
    session.add(dept)
    await session.flush()
    pos = Position(title="Project manager", department_id=dept.id, grade=1, weight=100, level=1)
    session.add(pos)
    await session.flush()

    employees: list[Employee] = []
    for idx in range(1, count + 1):
        emp = Employee(
            user_id=idx,
            first_name=f"User{idx}",
            last_name="Test",
            email=f"user{idx}@test.local",
            department_id=dept.id,
            position_id=pos.id,
            hire_date=date.today(),
            status="active",
        )
        session.add(emp)
        employees.append(emp)
    await session.commit()
    for item in employees:
        await session.refresh(item)
    return employees


async def _seed_pmos(session, count: int = 3) -> list[PMO]:
    pmos: list[PMO] = []
    for idx in range(1, count + 1):
        pmo = PMO(name=f"PMO {idx}", code=f"PMO-{idx}", status="active")
        session.add(pmo)
        pmos.append(pmo)
    await session.commit()
    for pmo in pmos:
        await session.refresh(pmo)
    return pmos


async def test_allocation_fields_round_trip(client, session):
    [employee] = await _seed_people(session, count=1)
    [pmo] = await _seed_pmos(session, count=1)

    created = await client.post(
        f"/api/hr/v1/pmo/{pmo.id}/members",
        json={
            "employee_id": employee.id,
            "membership_type": "permanent",
            "position_in_pmo": "Lead PM",
            "allocation_percent": 80,
            "is_primary": True,
        },
        headers=admin_headers(),
    )

    assert created.status_code == 201, created.text
    assert created.json()["allocation_percent"] == 80
    assert created.json()["is_primary"] is True

    listed = await client.get(f"/api/hr/v1/pmo/{pmo.id}/members", headers=admin_headers())
    assert listed.status_code == 200
    [member] = listed.json()
    assert member["allocation_percent"] == 80
    assert member["is_primary"] is True


async def test_second_active_primary_returns_409(client, session):
    employee1, employee2 = await _seed_people(session, count=2)
    [pmo] = await _seed_pmos(session, count=1)

    first = await client.post(
        f"/api/hr/v1/pmo/{pmo.id}/members",
        json={"employee_id": employee1.id, "is_primary": True},
        headers=admin_headers(),
    )
    assert first.status_code == 201, first.text

    second = await client.post(
        f"/api/hr/v1/pmo/{pmo.id}/members",
        json={"employee_id": employee2.id, "is_primary": True},
        headers=admin_headers(),
    )
    assert second.status_code == 409


async def test_closed_primary_allows_new_primary(client, session):
    employee1, employee2 = await _seed_people(session, count=2)
    [pmo] = await _seed_pmos(session, count=1)

    created = await client.post(
        f"/api/hr/v1/pmo/{pmo.id}/members",
        json={
            "employee_id": employee1.id,
            "is_primary": True,
            "from_date": (date.today() - timedelta(days=2)).isoformat(),
        },
        headers=admin_headers(),
    )
    assert created.status_code == 201, created.text
    member_id = created.json()["id"]

    closed = await client.patch(
        f"/api/hr/v1/pmo/{pmo.id}/members/{member_id}",
        json={"to_date": (date.today() - timedelta(days=1)).isoformat()},
        headers=admin_headers(),
    )
    assert closed.status_code == 200, closed.text

    next_primary = await client.post(
        f"/api/hr/v1/pmo/{pmo.id}/members",
        json={"employee_id": employee2.id, "is_primary": True},
        headers=admin_headers(),
    )
    assert next_primary.status_code == 201, next_primary.text


async def test_overallocation_returns_warning_header_without_blocking(client, session):
    [employee] = await _seed_people(session, count=1)
    pmo1, pmo2 = await _seed_pmos(session, count=2)

    first = await client.post(
        f"/api/hr/v1/pmo/{pmo1.id}/members",
        json={"employee_id": employee.id, "allocation_percent": 60},
        headers=admin_headers(),
    )
    assert first.status_code == 201, first.text

    second = await client.post(
        f"/api/hr/v1/pmo/{pmo2.id}/members",
        json={"employee_id": employee.id, "allocation_percent": 50},
        headers=admin_headers(),
    )
    assert second.status_code == 201, second.text
    assert second.headers["X-Allocation-Warning"] == "110"


async def test_invalid_member_dates_return_422(client, session):
    [employee] = await _seed_people(session, count=1)
    [pmo] = await _seed_pmos(session, count=1)

    res = await client.post(
        f"/api/hr/v1/pmo/{pmo.id}/members",
        json={
            "employee_id": employee.id,
            "from_date": date.today().isoformat(),
            "to_date": (date.today() - timedelta(days=1)).isoformat(),
        },
        headers=admin_headers(),
    )
    assert res.status_code == 422


async def test_employee_pmos_excludes_closed_pmo_and_inactive_membership(client, session):
    [employee] = await _seed_people(session, count=1)
    active_pmo, closed_pmo, inactive_pmo = await _seed_pmos(session, count=3)

    for pmo in (active_pmo, closed_pmo):
        res = await client.post(
            f"/api/hr/v1/pmo/{pmo.id}/members",
            json={"employee_id": employee.id, "allocation_percent": 40},
            headers=admin_headers(),
        )
        assert res.status_code == 201, res.text

    inactive = PMOMember(
        pmo_id=inactive_pmo.id,
        employee_id=employee.id,
        membership_type="consulting",
        from_date=date.today() - timedelta(days=3),
        to_date=date.today() - timedelta(days=1),
        allocation_percent=20,
        is_primary=False,
    )
    session.add(inactive)
    await session.commit()

    closed = await client.delete(f"/api/hr/v1/pmo/{closed_pmo.id}", headers=admin_headers())
    assert closed.status_code == 204

    lookup = await client.get(f"/api/hr/v1/employees/{employee.id}/pmos", headers=admin_headers())
    assert lookup.status_code == 200
    items = lookup.json()
    assert [item["pmo_id"] for item in items] == [active_pmo.id]


async def test_soft_delete_pmo_closes_active_members(client, session):
    employee1, employee2 = await _seed_people(session, count=2)
    [pmo] = await _seed_pmos(session, count=1)

    for employee in (employee1, employee2):
        res = await client.post(
            f"/api/hr/v1/pmo/{pmo.id}/members",
            json={"employee_id": employee.id},
            headers=admin_headers(),
        )
        assert res.status_code == 201, res.text

    deleted = await client.delete(f"/api/hr/v1/pmo/{pmo.id}", headers=admin_headers())
    assert deleted.status_code == 204

    rows = (
        await session.execute(select(PMOMember).where(PMOMember.pmo_id == pmo.id))
    ).scalars().all()
    assert rows
    assert {row.to_date for row in rows} == {date.today()}
