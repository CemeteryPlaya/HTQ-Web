"""Merge new staffing preset keys into existing leveled positions.

Revision ID: 021_merge_staffing_keys
Revises: 020_create_staffing
Create Date: 2026-05-30
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor

revision = "021_merge_staffing_keys"
down_revision = "020_create_staffing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from app.db import async_session_factory, engine
    from app.services.permission_backfill import merge_missing_preset_keys

    async def _run() -> None:
        async with async_session_factory() as session:
            await merge_missing_preset_keys(session)
        # The module-level engine pools connections bound to THIS loop; drop
        # them so the next data migration (fresh loop) doesn't inherit one.
        await engine.dispose()

    # alembic's online path already runs inside an event loop (env.py), so
    # asyncio.run() must happen on a thread that has no running loop.
    with ThreadPoolExecutor(max_workers=1) as pool:
        pool.submit(asyncio.run, _run()).result()


def downgrade() -> None:
    pass
