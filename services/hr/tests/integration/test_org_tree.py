"""Integration tests for the HR org-tree endpoint."""

from datetime import date

import pytest

from app.models.department import Department
from app.models.employee import Employee
from app.models.position import Position
from app.models.reporting_relation import ReportingRelation
from app.core.settings import settings
from tests.conftest import make_admin_token


pytestmark = pytest.mark.asyncio


def auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {make_admin_token(secret=settings.jwt_secret)}"}


async def _seed_position_tree(session):
    dept = Department(name="Leadership", path="company.leadership", unit_type="department")
    session.add(dept)
    await session.flush()

    ceo = Position(
        title="CEO",
        department_id=dept.id,
        grade=10,
        weight=0,
        level=1,
        is_active=True,
    )
    director = Position(
        title="Staff Director",
        department_id=dept.id,
        grade=8,
        weight=100,
        level=2,
        is_active=True,
    )
    session.add_all([ceo, director])
    await session.flush()

    manager = Employee(
        first_name="Erica",
        last_name="Romaguera",
        email="erica@example.test",
        department_id=dept.id,
        position_id=ceo.id,
        hire_date=date.today(),
        status="active",
    )
    subordinate = Employee(
        first_name="Russell",
        last_name="Ross",
        email="russell@example.test",
        department_id=dept.id,
        position_id=director.id,
        hire_date=date.today(),
        status="active",
    )
    session.add_all([manager, subordinate])
    await session.flush()
    session.add_all(
        [
            ReportingRelation(
                superior_position_id=ceo.id,
                subordinate_position_id=director.id,
                relation_type="direct",
                effective_from=date.today(),
            ),
        ]
    )
    await session.commit()
    return dept, ceo, director


async def test_positions_tree_connects_departments_to_employee_cards(client, session):
    dept, ceo, director = await _seed_position_tree(session)

    res = await client.get("/api/hr/v1/org/tree?mode=positions&depth=5", headers=auth_headers())

    assert res.status_code == 200, res.text
    body = res.json()
    nodes = {node["id"]: node for node in body["nodes"]}
    edges = {
        (edge["source"], edge["target"], edge["relation_type"])
        for edge in body["edges"]
    }

    assert f"dept_{dept.id}" in nodes
    assert f"pos_{ceo.id}" not in nodes
    assert nodes[f"dept_{dept.id}"]["meta"]["manager_name"] == "Erica Romaguera"
    assert nodes[f"pos_{director.id}"]["meta"]["holder_name"] == "Russell Ross"
    assert not any(node_id.startswith("emp_") for node_id in nodes)

    assert (f"dept_{dept.id}", f"pos_{director.id}", "direct") in edges
    assert not any(edge[0] == f"pos_{ceo.id}" or edge[1] == f"pos_{ceo.id}" for edge in edges)
    assert (f"dept_{dept.id}", f"pos_{director.id}", "membership") not in edges


async def test_both_mode_keeps_employees_inside_position_cards(client, session):
    _dept, ceo, _director = await _seed_position_tree(session)

    res = await client.get("/api/hr/v1/org/tree?mode=both&depth=5", headers=auth_headers())

    assert res.status_code == 200, res.text
    body = res.json()
    node_ids = [node["id"] for node in body["nodes"]]
    assert f"pos_{ceo.id}" not in node_ids
    assert not any(node_id.startswith("emp_") for node_id in node_ids)
