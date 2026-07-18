"""APScheduler jobs for CMS service.

Start the scheduler in a separate process or embed it in the main app lifespan.
Jobs are registered when ``start_scheduler()`` is called.
"""

import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import update

from app.db import async_session_factory
from app.models.news import News

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


async def news_scheduled_publish() -> None:
    """Publish news articles whose ``published_at`` has arrived.

    Runs every minute. Finds news where ``published=FALSE`` and
    ``published_at IS NOT NULL AND published_at <= now()`` and sets
    ``published = TRUE``.
    """
    async with async_session_factory() as session:
        from sqlalchemy import func

        stmt = (
            update(News)
            .where(
                News.published.is_(False),
                News.published_at.isnot(None),
                News.published_at <= func.now(),
            )
            .values(published=True)
            .execution_options(synchronize_session=False)
        )
        result = await session.execute(stmt)
        await session.commit()

        if result.rowcount > 0:
            logger.info(
                "news_scheduled_publish: published %d articles",
                result.rowcount,
            )


def start_scheduler() -> AsyncIOScheduler:
    """Register jobs and start the scheduler."""
    scheduler.add_job(
        news_scheduled_publish,
        CronTrigger(minute="*"),
        id="news_scheduled_publish",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("CMS scheduler started with jobs: news_scheduled_publish")
    return scheduler


def stop_scheduler() -> None:
    """Gracefully shut down the scheduler."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("CMS scheduler stopped")


async def _run_forever() -> None:
    """Start APScheduler inside a running loop — required under Python 3.14
    where ``asyncio.get_event_loop()`` no longer implicitly creates one."""
    start_scheduler()
    try:
        await asyncio.Event().wait()
    finally:
        stop_scheduler()


def main() -> None:
    """Run the CMS scheduler as a standalone process (`python -m app.workers.scheduler`)."""
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(_run_forever())
    except (KeyboardInterrupt, SystemExit):
        pass


if __name__ == "__main__":
    main()
