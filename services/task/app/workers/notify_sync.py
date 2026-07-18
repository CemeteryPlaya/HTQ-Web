"""Subscribe to messenger / email notify events and write Notification rows.

Channels:
- ``notify.new_chat_message`` — emitted by messenger-service after a new
  chat message lands. Payload carries ``recipient_ids`` (everyone except
  sender), sender name + a short preview. We create one Notification per
  recipient.
- ``notify.new_email_message`` — emitted by email-service after the
  sync layer UPSERTs a brand-new inbox message that wasn't already read.
  Single recipient (``user_id``).

Skipped recipients without a matching ``task_users`` replica row (the FK
on ``Notification.recipient_id`` would 23503). Such users haven't been
synced yet — the publisher events are fire-and-forget, so dropping them
silently is fine.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import redis.asyncio as aioredis
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import settings
from app.db import async_session_factory
from app.models.notification import Notification
from app.models.user_replica import User as UserReplica


log = structlog.get_logger(__name__)

CHANNEL_NEW_CHAT_MESSAGE = "notify.new_chat_message"
CHANNEL_NEW_EMAIL_MESSAGE = "notify.new_email_message"


async def _filter_known_users(
    session: AsyncSession, user_ids: list[int]
) -> set[int]:
    """Return only the user ids that exist in the local replica.

    Anything else would violate the recipient_id FK on insert.
    """
    if not user_ids:
        return set()
    rows = await session.execute(
        select(UserReplica.id).where(UserReplica.id.in_(user_ids))
    )
    return {row for (row,) in rows.all()}


async def _handle_chat_message(payload: dict[str, Any]) -> None:
    recipient_ids = [int(uid) for uid in payload.get("recipient_ids") or []]
    if not recipient_ids:
        return
    sender_name = (payload.get("sender_name") or "Кто-то").strip()
    sender_avatar_url = payload.get("sender_avatar_url") or None
    room_name = (payload.get("room_name") or "").strip()
    preview = (payload.get("preview") or "новое сообщение").strip()
    room_id = payload.get("room_id")
    sender_id = payload.get("sender_id")

    # No "прислал ..." preamble — the actor name already sits next to the verb
    # in every UI surface, so prefixing with a verb form just inflates the
    # text. Groups still carry their room name so the dropdown / history
    # row can show which chat the message landed in; the rich messenger toast
    # strips this prefix client-side to render only the body.
    if room_name:
        verb = f'в чате «{room_name}»: {preview}'
    else:
        verb = preview
    verb = verb[:200]

    async with async_session_factory() as session:
        known = await _filter_known_users(session, recipient_ids)
        if not known:
            return
        # Idempotency guard: if a notification with the same
        # (recipient, target, actor, verb) already landed within the last
        # 10 seconds, the publish must be a duplicate (Redis retry, dramatiq
        # retry, etc.). Skip it so the toast doesn't fire twice.
        from datetime import datetime, timedelta, timezone

        ten_sec_ago = datetime.now(timezone.utc) - timedelta(seconds=10)
        new_recipients: list[int] = []
        for uid in known:
            dup = await session.execute(
                select(Notification.id).where(
                    Notification.recipient_id == uid,
                    Notification.actor_id == (int(sender_id) if sender_id else None),
                    Notification.target_type == "messenger_room",
                    Notification.target_id == (int(room_id) if room_id is not None else None),
                    Notification.verb == verb,
                    Notification.created_at >= ten_sec_ago,
                ).limit(1)
            )
            if dup.scalar_one_or_none() is None:
                new_recipients.append(uid)
        if not new_recipients:
            log.info(
                "notify_chat_message_dedup",
                room_id=room_id,
                recipients=len(known),
            )
            return
        for uid in new_recipients:
            session.add(
                Notification(
                    recipient_id=uid,
                    actor_id=int(sender_id) if sender_id else None,
                    task_id=None,
                    target_type="messenger_room",
                    target_id=int(room_id) if room_id is not None else None,
                    verb=verb,
                    actor_avatar_url=sender_avatar_url,
                )
            )
        await session.commit()
        log.info(
            "notify_chat_message_persisted",
            recipients=len(new_recipients),
            room_id=room_id,
        )


async def _handle_email_message(payload: dict[str, Any]) -> None:
    user_id = payload.get("user_id")
    if not user_id:
        return
    subject = (payload.get("subject") or "(без темы)").strip()
    sender_name = (payload.get("sender_name") or "").strip()
    sender_email = (payload.get("sender_email") or "").strip()
    who = sender_name or sender_email or "Кто-то"
    verb = f'прислал письмо «{subject}»'
    verb = verb[:200]

    async with async_session_factory() as session:
        known = await _filter_known_users(session, [int(user_id)])
        if not known:
            return
        # Email message UUIDs don't fit into Notification.target_id (Integer
        # column) — we leave target_id NULL and rely on target_type to route
        # the click into /email when the SPA UI is wired for it.
        for uid in known:
            session.add(
                Notification(
                    recipient_id=uid,
                    actor_id=None,
                    task_id=None,
                    target_type="email_message",
                    target_id=None,
                    verb=f"{who} — {verb}"[:200],
                )
            )
        await session.commit()
        log.info(
            "notify_email_message_persisted",
            user_id=user_id,
            account_id=payload.get("account_id"),
        )


async def _handle(channel: str, raw: bytes | str) -> None:
    try:
        payload = json.loads(raw if isinstance(raw, str) else raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        log.warning("notify_sync_bad_json", channel=channel)
        return

    try:
        if channel == CHANNEL_NEW_CHAT_MESSAGE:
            await _handle_chat_message(payload)
        elif channel == CHANNEL_NEW_EMAIL_MESSAGE:
            await _handle_email_message(payload)
    except Exception as exc:  # noqa: BLE001
        log.exception("notify_sync_error", channel=channel, err=str(exc))


async def run_notify_sync_loop() -> None:
    """Long-running subscriber. Reconnects on transient errors."""
    backoff = 1
    while True:
        try:
            client = aioredis.Redis.from_url(settings.redis_url)
            pubsub = client.pubsub()
            await pubsub.subscribe(
                CHANNEL_NEW_CHAT_MESSAGE, CHANNEL_NEW_EMAIL_MESSAGE
            )
            log.info(
                "notify_sync_subscribed",
                channels=[CHANNEL_NEW_CHAT_MESSAGE, CHANNEL_NEW_EMAIL_MESSAGE],
            )
            backoff = 1
            async for msg in pubsub.listen():
                if msg.get("type") != "message":
                    continue
                channel = msg.get("channel")
                if isinstance(channel, bytes):
                    channel = channel.decode("utf-8")
                await _handle(channel, msg.get("data") or b"")
        except asyncio.CancelledError:
            try:
                await pubsub.unsubscribe()
                await client.aclose()
            except Exception:  # noqa: BLE001
                pass
            log.info("notify_sync_stopped")
            raise
        except Exception as exc:  # noqa: BLE001
            log.warning("notify_sync_disconnected", err=str(exc), backoff=backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)
