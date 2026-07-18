"""APScheduler-based periodic jobs for user-service.

Run as a separate process alongside the web/dramatiq workers:
    python -m app.workers.scheduler

Jobs:
- cleanup_stale_pending_registrations: daily, deletes PENDING users older than 30d.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import delete

from app.db import async_session_factory
from app.models.user import User, UserStatus

logger = logging.getLogger(__name__)

STALE_PENDING_THRESHOLD_DAYS = 30


async def cleanup_stale_pending_registrations() -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(days=STALE_PENDING_THRESHOLD_DAYS)
    async with async_session_factory() as session:
        result = await session.execute(
            delete(User)
            .where(User.status == UserStatus.PENDING, User.date_joined < cutoff)
            .returning(User.id)
        )
        deleted = result.scalars().all()
        await session.commit()
        if deleted:
            logger.info("cleanup_stale_pending_registrations removed %d users", len(deleted))


async def _run_forever() -> None:
    """Start APScheduler inside a running loop — required under Python 3.14."""
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        cleanup_stale_pending_registrations,
        "cron",
        hour=3,
        minute=0,
        id="cleanup_stale_pending_registrations",
    )
    scheduler.start()
    logger.info("user-service scheduler started")
    try:
        await asyncio.Event().wait()
    finally:
        scheduler.shutdown()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(_run_forever())
    except (KeyboardInterrupt, SystemExit):
        pass


if __name__ == "__main__":
    main()
