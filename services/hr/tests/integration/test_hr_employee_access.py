"""HR employee directory access levels."""

from datetime import date, datetime, timedelta, timezone

import jwt as pyjwt
import pytest
import pytest_asyncio

from app.models.department import Department
from app.models.employee import Employee
from app.models.position import Position


def _token(user_id: int, email: str, secret: str = "change-me") -> dict[str, str]:
    payload = {
        "sub": str(user_id),
        "user_id": user_id,
        "username": email.split("@", 1)[0],
        "email": email,
        "is_staff": False,
        "is_superuser": False,
        "is_admin": False,
        "iss": "htqweb-auth",
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
    }
    return {"Authorization": f"Bearer {pyjwt.encode(payload, secret, algorithm='HS256')}"}


@pytest_asyncio.fixture
async def hr_access_data(session):
    hr = Department(id=10, name="HR Department", path="root.hr")
    engineering = Department(id=20, name="Engineering", path="root.engineering")
    session.add_all([hr, engineering])
    await session.flush()

    positions = [
        Position(id=10, title="Junior HR Specialist", department_id=10, weight=10, level=3),
        Position(id=20, title="Middle HR Manager", department_id=10, weight=20, level=3),
        Position(id=30, title="Senior HR Specialist", department_id=10, weight=30, level=2),
        Position(id=40, title="CO HR", department_id=10, weight=40, level=1),
        Position(id=50, title="Backend Engineer", department_id=20, weight=50, level=3),
    ]
    session.add_all(positions)
    await session.flush()

    employees = [
        Employee(
            id=2,
            user_id=2,
            first_name="Junior",
            last_name="HR",
            email="junior.hr@test.local",
            department_id=10,
            position_id=10,
            hire_date=date(2024, 1, 1),
        ),
        Employee(
            id=3,
            user_id=3,
            first_name="Middle",
            last_name="HR",
            email="middle.hr@test.local",
            department_id=10,
            position_id=20,
            hire_date=date(2024, 1, 1),
        ),
        Employee(
            id=4,
            user_id=4,
            first_name="Senior",
            last_name="HR",
            email="senior.hr@test.local",
            department_id=10,
            position_id=30,
            hire_date=date(2024, 1, 1),
        ),
        Employee(
            id=5,
            user_id=5,
            first_name="Chief",
            last_name="HR",
            email="co.hr@test.local",
            department_id=10,
            position_id=40,
            hire_date=date(2024, 1, 1),
        ),
        Employee(
            id=6,
            user_id=6,
            first_name="Dev",
            last_name="One",
            email="dev@test.local",
            department_id=20,
            position_id=50,
            hire_date=date(2024, 1, 1),
        ),
    ]
    session.add_all(employees)
    await session.commit()


@pytest.mark.asyncio
async def test_hr_levels_are_resolved_from_employee_position(client, hr_access_data):
    cases = [
        (2, "junior.hr@test.local", "junior"),
        (3, "middle.hr@test.local", "middle"),
        (4, "senior.hr@test.local", "senior"),
        (5, "co.hr@test.local", "lead"),
    ]

    for user_id, email, expected in cases:
        resp = await client.get("/api/hr/v1/employees/hr-level/", headers=_token(user_id, email))
        assert resp.status_code == 200
        assert resp.json()["level"] == expected


@pytest.mark.asyncio
async def test_junior_sees_only_own_department_and_is_read_only(client, hr_access_data):
    listed = await client.get("/api/hr/v1/employees/?limit=100", headers=_token(2, "junior.hr@test.local"))
    assert listed.status_code == 200
    assert {item["email"] for item in listed.json()["items"]} == {
        "junior.hr@test.local",
        "middle.hr@test.local",
        "senior.hr@test.local",
        "co.hr@test.local",
    }

    update = await client.put(
        "/api/hr/v1/employees/2/",
        json={"phone": "+77000000000"},
        headers=_token(2, "junior.hr@test.local"),
    )
    assert update.status_code == 403


@pytest.mark.asyncio
async def test_middle_can_update_basic_own_department_but_not_transfer(client, hr_access_data):
    update = await client.put(
        "/api/hr/v1/employees/2/",
        json={"phone": "+77000000000"},
        headers=_token(3, "middle.hr@test.local"),
    )
    assert update.status_code == 200
    assert update.json()["phone"] == "+77000000000"

    transfer = await client.put(
        "/api/hr/v1/employees/2/",
        json={"department_id": 20},
        headers=_token(3, "middle.hr@test.local"),
    )
    assert transfer.status_code == 403

    hidden = await client.get("/api/hr/v1/employees/6/", headers=_token(3, "middle.hr@test.local"))
    assert hidden.status_code == 404


@pytest.mark.asyncio
async def test_senior_sees_all_but_cannot_delete(client, hr_access_data):
    listed = await client.get("/api/hr/v1/employees/?limit=100", headers=_token(4, "senior.hr@test.local"))
    assert listed.status_code == 200
    assert {item["email"] for item in listed.json()["items"]} == {
        "junior.hr@test.local",
        "middle.hr@test.local",
        "senior.hr@test.local",
        "co.hr@test.local",
        "dev@test.local",
    }

    delete = await client.delete("/api/hr/v1/employees/6/", headers=_token(4, "senior.hr@test.local"))
    assert delete.status_code == 403


@pytest.mark.asyncio
async def test_lead_has_full_employee_directory_access(client, hr_access_data):
    delete = await client.delete("/api/hr/v1/employees/6/", headers=_token(5, "co.hr@test.local"))
    assert delete.status_code == 204


@pytest.mark.asyncio
async def test_non_hr_employee_cannot_open_employee_directory(client, hr_access_data):
    resp = await client.get("/api/hr/v1/employees/", headers=_token(6, "dev@test.local"))
    assert resp.status_code == 403
