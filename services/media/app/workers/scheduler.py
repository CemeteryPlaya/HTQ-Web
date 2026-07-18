"""APScheduler jobs for media-service.

Run as separate process:
    python -m app.workers.scheduler
"""
import asyncio
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import delete

from app.core.logging import configure_logging, get_logger
from app.core.settings import settings
from app.db import async_session_factory
from app.models.audit_log import AuditLog

log = get_logger(__name__)

async def cleanup_orphan_files() -> None:
    """Check storage for files without metadata and delete them."""
    log.info("cleanup_orphan_files_run")
    # TODO: implement storage-specific cleanup

async def audit_log_compaction() -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.audit_log_retention_days)
    async with async_session_factory() as s:
        result = await s.execute(delete(AuditLog).where(AuditLog.created_at < cutoff))
        await s.commit()
        log.info("audit_log_compaction_run", deleted=result.rowcount)


async def purge_soft_deleted() -> None:
    """Drive ``actors.purge_soft_deleted`` from the scheduler.

    We import inside the function so the scheduler process can start without
    pulling in the dramatiq broker (which is wired up by the actors module).
    """
    from app.workers import actors

    await actors._purge_soft_deleted_impl()


async def _run_forever() -> None:
    """Start APScheduler inside a running loop — required under Python 3.14."""
    scheduler = AsyncIOScheduler()
    scheduler.add_job(cleanup_orphan_files, "cron", day_of_week="sun", hour=4, id="cleanup_orphan_files")
    scheduler.add_job(audit_log_compaction, "cron", hour=3, minute=30, id="audit_log_compaction")
    scheduler.add_job(purge_soft_deleted, "cron", hour=3, minute=0, id="purge_soft_deleted")
    scheduler.start()
    log.info("apscheduler_started")
    try:
        await asyncio.Event().wait()
    finally:
        scheduler.shutdown()


def main() -> None:
    configure_logging()
    try:
        asyncio.run(_run_forever())
    except (KeyboardInterrupt, SystemExit):
        pass

if __name__ == "__main__":
    main()
