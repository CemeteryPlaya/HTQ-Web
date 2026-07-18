"""Integration tests for position admin move/rebalance/level CRUD."""

import pytest
from sqlalchemy import select

from app.models.department import Department
from app.models.level_threshold import LevelThreshold
from app.models.position import Position
from app.models.position_weight_audit import PositionWeightAudit
from tests.conftest import admin_headers


pytestmark = pytest.mark.asyncio


async def _seed_thresholds(session, ranges: list[tuple[int, int, int, str]] | None = None) -> None:
    ranges = ranges or [
        (1, 0, 999, "L1"),
        (2, 1000, 1999, "L2"),
        (3, 2000, 2999, "L3"),
    ]
    for level, start, end, label in ranges:
        session.add(
            LevelThreshold(
                level_number=level,
                weight_from=start,
                weight_to=end,
                label=label,
                color="#3b82f6",
            )
        )
    await session.commit()


async def _seed_positions(session, weights: list[int]) -> list[Position]:
    dept = Department(name="Engineering", path="company.engineering", unit_type="department")
    session.add(dept)
    await session.flush()

    positions: list[Position] = []
    for idx, weight in enumerate(weights, start=1):
        pos = Position(
            title=f"Position {idx}",
            department_id=dept.id,
            grade=1,
            weight=weight,
            level=1 if weight < 1000 else 2,
        )
        session.add(pos)
        positions.append(pos)
    await session.commit()
    for pos in positions:
        await session.refresh(pos)
    return positions


async def test_move_position_writes_audit(client, session):
    await _seed_thresholds(session)
    p1, p2, p3 = await _seed_positions(session, [100, 300, 500])

    res = await client.patch(
        f"/api/hr/v1/positions/{p3.id}/move",
        json={"before_position_id": p1.id, "after_position_id": p2.id, "target_level": 1},
        headers=admin_headers(),
    )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["weight"] == 200
    assert body["level"] == 1

    audit = (
        await session.execute(
            select(PositionWeightAudit).where(PositionWeightAudit.position_id == p3.id)
        )
    ).scalar_one()
    assert audit.old_weight == 500
    assert audit.new_weight == 200
    assert audit.reason == "move"


async def test_rebalance_level_uses_two_phase_update_and_audits(client, session):
    await _seed_thresholds(session)
    positions = await _seed_positions(session, [100, 101, 102])

    res = await client.post(
        "/api/hr/v1/positions/rebalance",
        json={"level": 1},
        headers=admin_headers(),
    )

    assert res.status_code == 200, res.text
    assert res.json()["levels"] == {"1": 3}

    session.expire_all()
    rows = (
        await session.execute(select(Position).order_by(Position.weight.asc()))
    ).scalars().all()
    assert [p.weight for p in rows] == [0, 100, 200]

    audits = (
        await session.execute(
            select(PositionWeightAudit).where(
                PositionWeightAudit.position_id.in_([p.id for p in positions])
            )
        )
    ).scalars().all()
    assert len(audits) >= 2
    assert {a.reason for a in audits} == {"rebalance"}


async def test_level_crud_validates_overlap_and_color(client, session):
    await _seed_thresholds(session)

    overlap = await client.post(
        "/api/hr/v1/positions/levels/",
        json={
            "level_number": 10,
            "weight_from": 900,
            "weight_to": 1200,
            "label": "Overlap",
            "color": "#111111",
        },
        headers=admin_headers(),
    )
    assert overlap.status_code == 409

    invalid_color = await client.post(
        "/api/hr/v1/positions/levels/",
        json={
            "level_number": 10,
            "weight_from": 3000,
            "weight_to": 3999,
            "label": "Bad color",
            "color": "blue",
        },
        headers=admin_headers(),
    )
    assert invalid_color.status_code == 422

    created = await client.post(
        "/api/hr/v1/positions/levels/",
        json={
            "level_number": 10,
            "weight_from": 3000,
            "weight_to": 3999,
            "label": "Custom",
            "color": "#111111",
        },
        headers=admin_headers(),
    )
    assert created.status_code == 201, created.text
    assert created.json()["color"] == "#111111"


async def test_threshold_update_recomputes_cached_levels_and_audits(client, session):
    await _seed_thresholds(session, [(1, 0, 999, "L1"), (2, 1000, 1999, "L2")])
    [pos] = await _seed_positions(session, [1200])
    assert pos.level == 2

    res = await client.put(
        "/api/hr/v1/positions/levels/2",
        json={"weight_from": 1300, "weight_to": 1999, "label": "L2", "color": "#ef4444"},
        headers=admin_headers(),
    )

    assert res.status_code == 200, res.text
    await session.refresh(pos)
    assert pos.level == 5

    audit = (
        await session.execute(
            select(PositionWeightAudit).where(PositionWeightAudit.position_id == pos.id)
        )
    ).scalar_one()
    assert audit.old_level == 2
    assert audit.new_level == 5
    assert audit.reason == "threshold_change"
