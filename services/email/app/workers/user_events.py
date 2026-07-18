"""Subscriber for user-service lifecycle events.

Runs as an asyncio task spawned from the FastAPI lifespan (see main.py).
Listens to two Redis pub/sub channels published by user-service:

* ``user.deactivated`` — flip personal accounts ``is_active=False``
  (their sync stops; the row is kept so re-activation is one PATCH away)
  and archive any corporate mailbox if it isn't archived yet.
* ``user.deleted`` — start the 30-day purge clock by stamping
  ``archived_at`` on every mailbox the user owns. The scheduler picks
  these up in ``final_purge_archived_mailboxes``.

The loop reconnects with exponential backoff and never raises out of the
spawned task — failures are logged.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

import redis.asyncio as aioredis
import structlog
from sqlalchemy import select, update

from app.core.settings import settings
from app.db import async_session_factory
from app.models.account import EmailAccount
from app.models.mailbox import ProvisionedMailbox


log = structlog.get_logger(__name__)


CHANNEL_DEACTIVATED = "user.deactivated"
CHANNEL_DELETED = "user.deleted"


async def _archive_personal_accounts(user_id: int) -> int:
    """Mark every personal EmailAccount as inactive (stop their sync)."""
    async with async_session_factory() as session:
        result = await session.execute(
            update(EmailAccount)
            .where(
                EmailAccount.user_id == user_id,
                EmailAccount.type == "personal",
                EmailAccount.is_active.is_(True),
            )
            .values(is_active=False)
        )
        await session.commit()
        return int(result.rowcount or 0)


async def _archive_corporate_mailbox(user_id: int) -> int:
    """Set Mailcow mailbox status=archived (Mailcow API call done by actor)."""
    archived = 0
    async with async_session_factory() as session:
        rows = (
            await session.execute(
                select(ProvisionedMailbox).where(
                    ProvisionedMailbox.user_id == user_id,
                    ProvisionedMailbox.status == "active",
                )
            )
        ).scalars().all()
        for mb in rows:
            mb.status = "archived"
            mb.archived_at = datetime.now(timezone.utc)
            archived += 1
        if archived:
            await session.commit()
            try:
                from app.workers.mailbox_actors import archive_mailbox
                for mb in rows:
                    archive_mailbox.send(address=mb.address, mailbox_id=mb.id)
            except Exception as exc:  # noqa: BLE001
                log.warning("archive_mailbox_enqueue_failed", err=str(exc))
    return archived


async def _stamp_archived_at(user_id: int) -> int:
    """For mailboxes already archived but missing archived_at, set it now."""
    async with async_session_factory() as session:
        rows = (
            await session.execute(
                select(ProvisionedMailbox).where(
                    ProvisionedMailbox.user_id == user_id,
                    ProvisionedMailbox.status.in_(("archived", "active")),
                )
            )
        ).scalars().all()
        n = 0
        for mb in rows:
            if mb.status == "active":
                mb.status = "archived"
                n += 1
            if mb.archived_at is None:
                mb.archived_at = datetime.now(timezone.utc)
                n += 1
        if n:
            await session.commit()
        return n


async def _handle(channel: str, raw: bytes | str) -> None:
    try:
        payload = json.loads(raw if isinstance(raw, str) else raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        log.warning("user_event_bad_json", channel=channel)
        return

    user_id = int(payload.get("id", 0))
    if not user_id:
        return

    if channel == CHANNEL_DEACTIVATED:
        n_personal = await _archive_personal_accounts(user_id)
        n_corp = await _archive_corporate_mailbox(user_id)
        log.info(
            "user_deactivated_handled",
            user_id=user_id,
            personal_paused=n_personal,
            corporate_archived=n_corp,
        )
    elif channel == CHANNEL_DELETED:
        await _archive_personal_accounts(user_id)
        await _archive_corporate_mailbox(user_id)
        n = await _stamp_archived_at(user_id)
        log.info("user_deleted_handled", user_id=user_id, stamped=n)


async def run_user_events_loop() -> None:
    """Long-running subscriber. Restarts on transient errors."""
    backoff = 1
    while True:
        try:
            client = aioredis.from_url(settings.redis_url, decode_responses=True)
            pubsub = client.pubsub()
            await pubsub.subscribe(CHANNEL_DEACTIVATED, CHANNEL_DELETED)
            log.info("user_events_subscribed")
            backoff = 1
            async for msg in pubsub.listen():
                if msg.get("type") != "message":
                    continue
                channel = msg.get("channel")
                data = msg.get("data")
                try:
                    await _handle(channel, data)
                except Exception as exc:  # noqa: BLE001
                    log.exception("user_event_handler_error", channel=channel, err=str(exc))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.warning("user_events_loop_error", err=str(exc), backoff=backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)
