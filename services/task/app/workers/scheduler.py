"""APScheduler-based periodic jobs for task-service.

Run as a separate process:
    python -m app.workers.scheduler

Jobs:
- task_deadline_reminder: hourly, finds tasks due within 24h and enqueues notifications.
"""

import asyncio
import json
import logging
from datetime import date, datetime, timedelta, timezone

import redis.asyncio as aioredis
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import and_, select

from app.core.settings import settings
from app.db import async_session_factory
from app.models.calendar import CalendarEvent, CalendarEventParticipant
from app.models.task import Status, Task
from app.workers.actors import notification_dispatch

logger = logging.getLogger(__name__)


async def task_deadline_reminder() -> None:
    today = date.today()
    horizon = today + timedelta(days=1)
    async with async_session_factory() as session:
        result = await session.execute(
            select(Task).where(
                and_(
                    Task.due_date.is_not(None),
                    Task.due_date <= horizon,
                    Task.status.notin_([Status.DONE, Status.CANCELLED]),
                    Task.is_deleted.is_(False),
                )
            )
        )
        tasks = result.scalars().all()

    for task in tasks:
        if not task.assignee_id:
            continue
        notification_dispatch.send(
            {
                "recipient_id": task.assignee_id,
                "actor_id": None,
                "task_id": task.id,
                "verb": f"task_due_{(task.due_date - today).days}d",
            }
        )
    logger.info("task_deadline_reminder enqueued %d notifications", len(tasks))


async def _publish_redis(channel: str, payload: dict) -> None:
    """Fire-and-forget JSON publish to Redis. Failure → log, never raise."""
    try:
        client = aioredis.Redis.from_url(settings.redis_url)
        try:
            await client.publish(channel, json.dumps(payload, default=str))
        finally:
            await client.aclose()
    except Exception as exc:  # noqa: BLE001
        logger.warning("scheduler_publish_failed channel=%s err=%s", channel, exc)


# Track which (event_id, user_id) pairs we already notified so the job
# doesn't spam the same person every 5 minutes for the same event.
# Bounded to the most recent 5000 pairs — older entries are discarded.
_calendar_reminders_sent: list[tuple[int, int]] = []
_CALENDAR_REMINDER_MEMORY = 5000


def _remember_reminder(event_id: int, user_id: int) -> bool:
    """Return True if this is a new (event,user) pair we should notify on."""
    pair = (event_id, user_id)
    if pair in _calendar_reminders_sent:
        return False
    _calendar_reminders_sent.append(pair)
    if len(_calendar_reminders_sent) > _CALENDAR_REMINDER_MEMORY:
        del _calendar_reminders_sent[: len(_calendar_reminders_sent) - _CALENDAR_REMINDER_MEMORY]
    return True


async def calendar_event_reminder() -> None:
    """Find events starting within the next 15 minutes and emit a reminder
    for every participant who hasn't been notified yet.

    Publishes ``notify.calendar_event_reminder`` for each participant; the
    messenger bot subscriber turns each into a DM from the Календарь bot.
    """
    now = datetime.now(timezone.utc)
    horizon = now + timedelta(minutes=15)
    async with async_session_factory() as session:
        stmt = (
            select(CalendarEvent, CalendarEventParticipant.user_id)
            .join(
                CalendarEventParticipant,
                CalendarEvent.id == CalendarEventParticipant.event_id,
            )
            .where(
                CalendarEvent.start_at >= now,
                CalendarEvent.start_at <= horizon,
                CalendarEventParticipant.rsvp_status.in_(("pending", "accepted")),
            )
        )
        rows = (await session.execute(stmt)).all()

    delivered = 0
    for event, user_id in rows:
        if not _remember_reminder(event.id, int(user_id)):
            continue
        starts_in = max(0, int((event.start_at - now).total_seconds() // 60))
        await _publish_redis(
            "notify.calendar_event_reminder",
            {
                "user_id": int(user_id),
                "event_id": event.id,
                "title": event.title,
                "starts_in_minutes": starts_in,
            },
        )
        delivered += 1
    if delivered:
        logger.info("calendar_event_reminder fired count=%d", delivered)


async def _run_forever() -> None:
    """Start APScheduler inside a running asyncio loop and block until
    cancelled. Python 3.14 removed the implicit ``asyncio.get_event_loop()``
    on the main thread, so ``AsyncIOScheduler.start()`` must execute inside
    an already-running loop (``asyncio.run`` provides one)."""
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        task_deadline_reminder,
        "cron",
        minute=0,
        id="task_deadline_reminder",
    )
    # Every 5 minutes — picks up events with start within the next 15 min.
    scheduler.add_job(
        calendar_event_reminder,
        "interval",
        minutes=5,
        id="calendar_event_reminder",
    )
    scheduler.start()
    logger.info("task-service scheduler started")
    try:
        await asyncio.Event().wait()  # park forever
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
