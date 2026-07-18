"""Backfill position.permissions[] from level presets.

Revision ID: 014_backfill_position_perms
Revises: 013
Create Date: 2026-05-29
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor

# NB: alembic's version table stores version_num as VARCHAR(32) — keep ids short.
revision = "014_backfill_position_perms"
down_revision = "013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from app.db import async_session_factory, engine
    from app.services.permission_backfill import backfill_position_permissions

    async def _run() -> None:
        async with async_session_factory() as session:
            await backfill_position_permissions(session)
        # The module-level engine pools connections bound to THIS loop; drop
        # them so the next data migration (fresh loop) doesn't inherit one.
        await engine.dispose()

    # alembic's online path already runs inside an event loop (env.py), so
    # asyncio.run() must happen on a thread that has no running loop.
    with ThreadPoolExecutor(max_workers=1) as pool:
        pool.submit(asyncio.run, _run()).result()


def downgrade() -> None:
    pass
