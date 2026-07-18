"""Queue ``make_variants`` for every image that lacks variants.

Run after migration 0005 once the worker is up::

    docker compose exec media-service python -m scripts.enqueue_backfill

Idempotent — already-generated variants are skipped inside the actor.
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db import async_session_factory
from app.models.file_metadata import FileMetadata
from app.workers.actors import make_variants


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger(__name__)


async def enqueue() -> int:
    async with async_session_factory() as session:
        rows = await session.execute(
            select(FileMetadata)
            .options(selectinload(FileMetadata.variants))
            .where(
                FileMetadata.kind == "image",
                FileMetadata.deleted_at.is_(None),
            )
        )
        sent = 0
        for meta in rows.scalars().all():
            existing = {v.variant for v in meta.variants}
            # Defer scope-policy lookup to the actor; we just want to nudge
            # everything that doesn't have *any* variant yet.
            if existing:
                continue
            make_variants.send(str(meta.id))
            sent += 1
    log.info("enqueued %d make_variants tasks", sent)
    return sent


if __name__ == "__main__":
    asyncio.run(enqueue())
