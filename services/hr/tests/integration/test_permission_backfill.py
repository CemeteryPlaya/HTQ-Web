"""Backfill seeds position.permissions[] from level presets, idempotently."""

import pytest

from app.models.department import Department
from app.models.position import Position
from app.auth.permissions import LEVEL_PRESETS
from app.services.permission_backfill import backfill_position_permissions

pytestmark = pytest.mark.asyncio


async def _dept(session):
    d = Department(name="D", path="d")
    session.add(d)
    await session.flush()
    return d


async def test_backfill_fills_leveled_position(session):
    d = await _dept(session)
    p = Position(title="HR Senior", department_id=d.id, weight=40,
                 permissions={"hr_level": "senior", "permissions": []})
    session.add(p)
    await session.flush()

    n = await backfill_position_permissions(session)
    await session.refresh(p)
    assert n == 1
    assert set(p.permissions["permissions"]) == set(LEVEL_PRESETS["senior"])


async def test_backfill_skips_nonempty(session):
    d = await _dept(session)
    p = Position(title="Custom", department_id=d.id, weight=41,
                 permissions={"hr_level": "senior", "permissions": ["hr.employees.view"]})
    session.add(p)
    await session.flush()

    await backfill_position_permissions(session)
    await session.refresh(p)
    assert p.permissions["permissions"] == ["hr.employees.view"]  # untouched


async def test_backfill_ignores_positions_without_level(session):
    d = await _dept(session)
    p = Position(title="Plain", department_id=d.id, weight=42, permissions=None)
    session.add(p)
    await session.flush()

    await backfill_position_permissions(session)
    await session.refresh(p)
    assert p.permissions is None


from app.services.permission_backfill import merge_missing_preset_keys


async def test_merge_adds_missing_card_keys_without_dropping_others(session):
    d = Department(name="D2", path="d2"); session.add(d); await session.flush()
    p = Position(title="Sr", department_id=d.id, weight=43,
                 permissions={"hr_level": "senior", "permissions": ["hr.employees.view", "custom.extra"]})
    session.add(p); await session.flush()

    n = await merge_missing_preset_keys(session)
    await session.refresh(p)
    keys = set(p.permissions["permissions"])
    assert "hr.card.financial.view" in keys
    assert "hr.employees.view" in keys
    assert "custom.extra" in keys
    assert n >= 1
