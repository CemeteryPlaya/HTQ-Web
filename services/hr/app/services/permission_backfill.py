"""Seed Position.permissions[] from level presets (idempotent).

Only fills positions that have an explicit ``hr_level`` but an EMPTY
``permissions`` list. Positions with a non-empty list are left untouched
(admins may have customised them); positions without a level are skipped.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.auth.permissions import expand_level
from app.models.position import Position


async def backfill_position_permissions(session: AsyncSession) -> int:
    """Return the number of positions updated."""
    positions = (await session.execute(select(Position))).scalars().all()
    updated = 0
    for pos in positions:
        perms = pos.permissions
        if not isinstance(perms, dict):
            continue
        level = perms.get("hr_level")
        existing = perms.get("permissions")
        if not level:
            continue
        if isinstance(existing, list) and existing:
            continue  # already customised — don't touch
        preset = sorted(expand_level(level))
        if not preset:
            continue
        pos.permissions = {"hr_level": level, "permissions": preset}
        flag_modified(pos, "permissions")
        updated += 1
    if updated:
        await session.commit()
    return updated


async def merge_missing_preset_keys(session: AsyncSession) -> int:
    """Union each leveled position's permissions[] with its level preset.

    Adds keys the preset now contains but the stored set lacks (e.g. new
    card keys). Never removes existing keys (including custom non-preset ones).
    Returns the number of positions changed.
    """
    positions = (await session.execute(select(Position))).scalars().all()
    changed = 0
    for pos in positions:
        perms = pos.permissions
        if not isinstance(perms, dict):
            continue
        level = perms.get("hr_level")
        if not level:
            continue
        existing = set(perms.get("permissions") or [])
        preset = expand_level(level)
        missing = preset - existing
        if not missing:
            continue
        pos.permissions = {"hr_level": level, "permissions": sorted(existing | preset)}
        flag_modified(pos, "permissions")
        changed += 1
    if changed:
        await session.commit()
    return changed
