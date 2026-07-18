"""APScheduler jobs for messenger-service.

Run as separate process:
    python -m app.workers.scheduler
"""
import asyncio
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import delete

from app.core.logging import configure_logging, get_logger
from app.core.settings import settings
from app.db import async_session_factory
from app.models.audit_log import AuditLog
from app.services.history_archive import archive_recent_history

log = get_logger(__name__)

async def archive_old_messages() -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(days=90)
    async with async_session_factory():
        # MVP: только лог. TODO перенос в cold storage.
        log.info("archive_old_messages_run", cutoff=cutoff.isoformat())

async def cleanup_presence() -> None:
    # Redis TTL handling — noop (presence хранится в Redis с TTL).
    log.info("cleanup_presence_run")

async def audit_log_compaction() -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.audit_log_retention_days)
    async with async_session_factory() as s:
        result = await s.execute(delete(AuditLog).where(AuditLog.created_at < cutoff))
        await s.commit()
        log.info("audit_log_compaction_run", deleted=result.rowcount)

async def archive_history_to_s3() -> None:
    """Weekly room history dump → S3 (chats/<room>/history/YYYY/MM/DD.jsonl)."""
    summary = await archive_recent_history(days=7)
    log.info("history_archive_done", **summary)

async def _run_forever() -> None:
    """Start APScheduler inside a running loop — required under Python 3.14."""
    scheduler = AsyncIOScheduler()
    scheduler.add_job(archive_old_messages, "cron", hour=3, minute=15, id="archive_old_messages")
    scheduler.add_job(cleanup_presence, "cron", minute="*/5", id="cleanup_presence")
    scheduler.add_job(audit_log_compaction, "cron", hour=3, minute=30, id="audit_log_compaction")
    # Weekly archive — Saturday 04:30 GMT+5 by default. The cron expression
    # is timezone-aware; APScheduler handles DST itself even though Asia/Almaty
    # has no DST today.
    scheduler.add_job(
        archive_history_to_s3,
        CronTrigger(
            day_of_week=settings.history_archive_cron_day,
            hour=settings.history_archive_cron_hour,
            minute=settings.history_archive_cron_minute,
            timezone=settings.history_archive_timezone,
        ),
        id="history_archive_to_s3",
    )
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
