"""Identity sync: user.upserted propagates name/email/phone/avatar to Employee."""

import pytest
from datetime import date

from app.models.department import Department
from app.models.position import Position
from app.models.employee import Employee
from app.workers.user_identity_sync import _apply_user_event

pytestmark = pytest.mark.asyncio


async def _seed_employee(session, *, user_id, **overrides):
    dept = Department(name="Eng", path="eng")
    session.add(dept)
    await session.flush()
    pos = Position(title="Engineer", department_id=dept.id, weight=50)
    session.add(pos)
    await session.flush()
    emp = Employee(
        user_id=user_id,
        first_name=overrides.get("first_name", "Old"),
        last_name=overrides.get("last_name", "Name"),
        email=overrides.get("email", "old@test.local"),
        phone=overrides.get("phone"),
        department_id=dept.id,
        position_id=pos.id,
        hire_date=date(2020, 1, 1),
        status="active",
    )
    session.add(emp)
    await session.flush()
    return emp


async def test_sync_updates_linked_employee_identity(session):
    emp = await _seed_employee(session, user_id=42)
    await _apply_user_event(
        session,
        {
            "id": 42,
            "first_name": "New",
            "last_name": "Person",
            "email": "new@test.local",
            "phone": "+7 700 000 0000",
            "avatar_url": "/api/media/v1/files/abc",
        },
    )
    await session.refresh(emp)
    assert emp.first_name == "New"
    assert emp.last_name == "Person"
    assert emp.email == "new@test.local"
    assert emp.phone == "+7 700 000 0000"
    assert emp.avatar_url == "/api/media/v1/files/abc"


async def test_sync_ignores_unlinked_user(session):
    emp = await _seed_employee(session, user_id=None)
    await _apply_user_event(
        session,
        {"id": 999, "first_name": "X", "last_name": "Y", "email": "x@y.z"},
    )
    await session.refresh(emp)
    assert emp.first_name == "Old"  # untouched


async def test_sync_noop_when_unchanged_returns_false(session):
    emp = await _seed_employee(
        session, user_id=7, first_name="Same", last_name="Value", email="s@v.z"
    )
    changed = await _apply_user_event(
        session,
        {"id": 7, "first_name": "Same", "last_name": "Value", "email": "s@v.z"},
    )
    assert changed is False


async def test_sync_clears_nullable_phone(session):
    emp = await _seed_employee(session, user_id=55, phone="+7 700 111 2222")
    changed = await _apply_user_event(
        session,
        {"id": 55, "phone": ""},
    )
    await session.refresh(emp)
    assert changed is True
    assert emp.phone == ""
