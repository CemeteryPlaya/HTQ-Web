"""Publish notification events to Redis pub/sub.

Messenger emits ``notify.new_chat_message`` for each newly-saved message
to a room with ≥ 2 participants. A subscriber in task-service writes a
``Notification`` row per recipient — the existing dropdown + history page
+ toast viewer surfaces it automatically.

Decoupled via Redis on purpose: messenger doesn't need to know about
task-service's DB or schema, and the subscriber side stays an internal
detail of task-service.
"""

from __future__ import annotations

import json
from typing import Any

import redis.asyncio as aioredis
import structlog

from app.core.settings import settings


log = structlog.get_logger(__name__)

CHANNEL_NEW_CHAT_MESSAGE = "notify.new_chat_message"


async def publish_notify_event(channel: str, payload: dict[str, Any]) -> None:
    """Fire-and-forget JSON publish to the given Redis channel.

    Connection failures only get logged — we never want a notification
    publish to abort the underlying user action (saving a message).
    """
    try:
        client = aioredis.Redis.from_url(settings.redis_url)
        try:
            await client.publish(channel, json.dumps(payload, default=str))
        finally:
            await client.aclose()
    except Exception as exc:  # noqa: BLE001
        log.warning("notify_publish_failed", channel=channel, err=str(exc))
