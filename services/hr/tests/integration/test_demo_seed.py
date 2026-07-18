"""Regression tests for the demo-data seeder used by the lifespan hook."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.models.department import Department
from app.models.employee import Employee
from app.models.pmo import PMO, PMOMember
from app.models.position import Position
from app.services.demo_seed_service import (
    DEPARTMENTS,
    EMPLOYEES,
    POSITIONS,
    PMOS,
    is_demo_data_present,
    reset_demo_data,
    seed_demo_data,
)


pytestmark = pytest.mark.asyncio


async def test_seed_populates_expected_counts(session):
    assert await is_demo_data_present(session) is False

    result = await seed_demo_data(session)
    await session.commit()

    assert result["status"] == "seeded"
    assert result["departments"] == len(DEPARTMENTS)
    assert result["positions"] == len(POSITIONS)
    assert result["employees"] == len(EMPLOYEES)
    assert result["pmos"] == len(PMOS)

    # Real DB matches what the function reported.
    n_dept = (await session.execute(select(func.count(Department.id)))).scalar()
    n_pos = (await session.execute(select(func.count(Position.id)))).scalar()
    n_emp = (await session.execute(select(func.count(Employee.id)))).scalar()
    n_pmo = (await session.execute(select(func.count(PMO.id)))).scalar()
    assert n_dept >= len(DEPARTMENTS)
    assert n_pos >= len(POSITIONS)
    assert n_emp >= len(EMPLOYEES)
    assert n_pmo >= len(PMOS)


async def test_second_run_is_a_noop(session):
    await seed_demo_data(session)
    await session.commit()

    result = await seed_demo_data(session)
    await session.commit()
    assert result["status"] == "skipped"


async def test_force_reseeds_without_duplicates(session):
    await seed_demo_data(session)
    await session.commit()

    n_emp_before = (await session.execute(select(func.count(Employee.id)))).scalar()
    result = await seed_demo_data(session, force=True)
    await session.commit()

    assert result["status"] == "seeded"
    n_emp_after = (await session.execute(select(func.count(Employee.id)))).scalar()
    assert n_emp_after == n_emp_before, "force-reseed must upsert, not duplicate"


async def test_seed_marks_one_primary_per_pmo(session):
    await seed_demo_data(session)
    await session.commit()

    pmos = (await session.execute(select(PMO))).scalars().all()
    for pmo in pmos:
        primaries = (
            await session.execute(
                select(func.count(PMOMember.id)).where(
                    PMOMember.pmo_id == pmo.id,
                    PMOMember.is_primary.is_(True),
                    PMOMember.to_date.is_(None),
                )
            )
        ).scalar()
        assert primaries == 1, f"PMO {pmo.code}: expected 1 active primary, got {primaries}"


async def test_seed_creates_overallocation_case(session):
    """senior.fe1 sits in DIGITAL (50%) + RECRUIT (60%) = 110%; UI shows warning."""
    await seed_demo_data(session)
    await session.commit()

    emp = (
        await session.execute(
            select(Employee).where(Employee.email == "senior.fe1@hitech.demo")
        )
    ).scalar_one()
    total = (
        await session.execute(
            select(func.sum(PMOMember.allocation_percent)).where(
                PMOMember.employee_id == emp.id,
                PMOMember.to_date.is_(None),
            )
        )
    ).scalar() or 0
    assert total > 100, f"expected over-allocation seed case, got {total}%"


async def test_reset_removes_only_demo_rows(session):
    await seed_demo_data(session)
    await session.commit()
    assert await is_demo_data_present(session) is True

    # A real (non-demo) employee that must survive the reset.
    keeper_dept = (
        await session.execute(select(Department).where(Department.path == "hq"))
    ).scalar_one()
    keeper_pos = (
        await session.execute(select(Position).where(Position.title == "CTO"))
    ).scalar_one_or_none()
    # If we don't have a non-seed Position to reuse, create a foreign one.
    if keeper_pos is None:
        keeper_pos = Position(
            title="Внешний сотрудник",
            department_id=keeper_dept.id,
            weight=999,
            level=5,
            grade=1,
            is_active=True,
        )
        session.add(keeper_pos)
        await session.flush()
    real_emp = Employee(
        first_name="Реальный",
        last_name="Сотрудник",
        email="real.employee@hitech.kz",  # NOT @hitech.demo
        department_id=keeper_dept.id,
        position_id=keeper_pos.id,
        hire_date=keeper_dept.created_at.date() if keeper_dept.created_at else None,
        status="active",
    )
    from datetime import date as _date
    real_emp.hire_date = _date.today()
    session.add(real_emp)
    await session.commit()

    await reset_demo_data(session)
    await session.commit()

    assert await is_demo_data_present(session) is False
    survivor = (
        await session.execute(
            select(Employee).where(Employee.email == "real.employee@hitech.kz")
        )
    ).scalar_one_or_none()
    assert survivor is not None, "reset must not delete non-demo rows"
