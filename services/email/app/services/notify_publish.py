"""Publish notification events to Redis pub/sub.

Email-service emits ``notify.new_email_message`` when a fresh INBOX
message is synced from any provider (Gmail history, Microsoft Graph
delta, Mailcow IMAP IDLE). A subscriber in task-service writes a
``Notification`` row — the existing dropdown / toast / history page UI
picks it up automatically.

Decoupled via Redis on purpose: email-service knows nothing about
task-service's DB or schema.
"""

from __future__ import annotations

import json
from typing import Any

import redis.asyncio as aioredis
import structlog

from app.core.settings import settings


log = structlog.get_logger(__name__)

CHANNEL_NEW_EMAIL_MESSAGE = "notify.new_email_message"


async def publish_notify_event(channel: str, payload: dict[str, Any]) -> None:
    """Fire-and-forget JSON publish. Failures are logged, never raised."""
    try:
        client = aioredis.Redis.from_url(settings.redis_url)
        try:
            await client.publish(channel, json.dumps(payload, default=str))
        finally:
            await client.aclose()
    except Exception as exc:  # noqa: BLE001
        log.warning("notify_publish_failed", channel=channel, err=str(exc))
