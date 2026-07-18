"""Dramatiq actors for bot DM delivery + deferred reminders/escalations."""

import asyncio
import logging

import dramatiq

from app.core.settings import settings
from app.services.messenger_client import MessengerS2SError, post_bot_message_sync
# Import the broker module so this actor binds to it on import.
from app.workers import actors as _actors  # noqa: F401

log = logging.getLogger(__name__)


@dramatiq.actor(max_retries=5, min_backoff=2000, max_backoff=60_000)
def send_bot_message(bot: str, user_id: int, text: str, metadata: dict | None = None) -> None:
    try:
        post_bot_message_sync(bot=bot, user_id=user_id, text=text, metadata=metadata)
    except MessengerS2SError as exc:
        msg = str(exc)
        # 4xx ('rejected payload') → swallow; 5xx/unreachable → re-raise to retry
        if "rejected payload" in msg:
            log.warning("bot_dispatch_dropped recipient=%s reason=%s", user_id, msg)
            return
        raise


# ─── Deferred reminders + escalations ────────────────────────────────────
# We don't poll the DB on a schedule. When an approval slot is created,
# the runtime enqueues these two actors with `delay=…` matching the
# reminder / escalation cadence. The actor wakes up, checks ``acted_at``;
# if the approver has already responded it's a no-op. Otherwise it
# dispatches the bot message and re-schedules itself.


async def _run_reminder(action_id: int) -> None:
    from sqlalchemy import select

    from app.db import async_session_factory
    from app.models.approval_action import ApprovalAction
    from app.models.request_instance import RequestInstance, RequestStatus
    from app.services.dispatch import dispatch_event

    async with async_session_factory() as session:
        action = await session.get(ApprovalAction, action_id)
        if action is None or action.acted_at is not None:
            return  # acted on; nothing to do
        inst = await session.get(RequestInstance, action.request_id)
        if inst is None or inst.status != RequestStatus.PENDING.value:
            return  # finalized somehow; skip
        if inst.current_node_id != action.node_id:
            return  # moved past this node
        # Send reminder
        await dispatch_event(session, inst, "reminder", [action.approver_id],
                             approver_id=action.approver_id)
        if action.reminders_sent < settings.requests_reminder_max_iterations:
            action.reminders_sent += 1
            await session.commit()
            schedule_reminder.send_with_options(
                args=[action_id],
                delay=settings.requests_reminder_after_hours * 3600 * 1000,
            )
        else:
            await session.commit()


async def _run_escalation(action_id: int) -> None:
    from app.db import async_session_factory
    from app.models.approval_action import ApprovalAction
    from app.models.request_instance import RequestInstance, RequestStatus
    from app.services.dispatch import dispatch_event

    async with async_session_factory() as session:
        action = await session.get(ApprovalAction, action_id)
        if action is None or action.acted_at is not None:
            return
        inst = await session.get(RequestInstance, action.request_id)
        if inst is None or inst.status != RequestStatus.PENDING.value:
            return
        if inst.current_node_id != action.node_id:
            return
        inst.requires_admin_attention = True
        await dispatch_event(session, inst, "escalation", [action.approver_id],
                             approver_id=action.approver_id)
        await session.commit()


@dramatiq.actor(max_retries=3, min_backoff=2000, max_backoff=60_000)
def schedule_reminder(action_id: int) -> None:
    asyncio.run(_run_reminder(action_id))


@dramatiq.actor(max_retries=3, min_backoff=2000, max_backoff=60_000)
def schedule_escalation(action_id: int) -> None:
    asyncio.run(_run_escalation(action_id))


# ─── Nightly stats reconciliation ────────────────────────────────────────


async def _run_rollup_stats_daily() -> None:
    from app.db import async_session_factory
    from app.services.stats_rollup import recompute_window

    async with async_session_factory() as session:
        touched = await recompute_window(session, days=7)
        await session.commit()
        log.info("stats_rollup_done rows=%d", touched)


def _next_03_local_ms() -> int:
    """Milliseconds until the next 03:00 UTC."""
    from datetime import datetime, time, timedelta, timezone
    now = datetime.now(timezone.utc)
    target = datetime.combine(now.date(), time(3, 0), tzinfo=timezone.utc)
    if target <= now:
        target += timedelta(days=1)
    return int((target - now).total_seconds() * 1000)


@dramatiq.actor(max_retries=3, min_backoff=10_000, max_backoff=300_000)
def rollup_stats_daily() -> None:
    """Reconcile the last 7 days of ``request_stats_daily`` and re-schedule
    itself for the next 03:00 UTC.

    Triggered first time from the service lifespan; from then on it
    re-queues itself, so no APScheduler / cron is required."""
    asyncio.run(_run_rollup_stats_daily())
    rollup_stats_daily.send_with_options(delay=_next_03_local_ms())
