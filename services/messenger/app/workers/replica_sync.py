"""User-replica sync — listens for `user.upserted` / `user.deactivated`.

User-service publishes lifecycle events to Redis pub/sub when a user is
created, approved, suspended, or rejected. We mirror the relevant fields
into the local `messenger.chat_user_replicas` table so the chat domain has
zero cross-schema joins (see ChatUserReplica).

The loop runs as a background task spawned from the FastAPI lifespan.
A single subscriber per service replica is fine because Redis pub/sub
fan-outs to all subscribers; if we scale the messenger service horizontally
each replica gets its own copy of the event.

To prime the replica from scratch (initial migration / disaster recovery),
fire the `rebuild_replicas` actor — it pulls every user via the admin API.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import redis.asyncio as aioredis
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import settings
from app.db import async_session_factory
from app.models.domain import ChatUserReplica


log = structlog.get_logger(__name__)


async def _upsert_replica(session: AsyncSession, payload: dict[str, Any]) -> None:
    user_id = int(payload["id"])
    existing = await session.get(ChatUserReplica, user_id)
    fields = {
        "username": payload.get("username") or "",
        "first_name": payload.get("first_name") or "",
        "last_name": payload.get("last_name") or "",
        "avatar_url": payload.get("avatar_url"),
        "is_active": bool(payload.get("is_active", True)),
    }
    if existing is not None:
        for k, v in fields.items():
            setattr(existing, k, v)
    else:
        session.add(ChatUserReplica(id=user_id, **fields))
    await session.commit()


async def _deactivate_replica(session: AsyncSession, user_id: int) -> None:
    existing = await session.get(ChatUserReplica, user_id)
    if existing is None:
        return
    existing.is_active = False
    await session.commit()


async def _handle(channel: str, raw: bytes | str) -> None:
    try:
        payload = json.loads(raw if isinstance(raw, str) else raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        log.warning("replica_sync_bad_json", channel=channel, raw=str(raw)[:100])
        return

    async with async_session_factory() as session:
        try:
            if channel == "user.upserted":
                await _upsert_replica(session, payload)
            elif channel == "user.deactivated":
                await _deactivate_replica(session, int(payload.get("id", 0)))
            else:
                return
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            log.exception("replica_sync_error", channel=channel, err=str(exc))
            return

    log.info("replica_synced", channel=channel, user_id=payload.get("id"))


async def run_user_replica_sync_loop() -> None:
    """Long-running task — subscribes to Redis pub/sub for user updates.

    Restarts on transient errors with exponential backoff. Cancellation
    propagates from the FastAPI lifespan and ends the loop cleanly.
    """
    backoff = 1
    while True:
        try:
            client = aioredis.Redis.from_url(settings.redis_url)
            pubsub = client.pubsub()
            await pubsub.subscribe("user.upserted", "user.deactivated")
            log.info("replica_sync_subscribed", channels=["user.upserted", "user.deactivated"])
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
                await client.close()
            except Exception:  # noqa: BLE001
                pass
            log.info("replica_sync_stopped")
            raise
        except Exception as exc:  # noqa: BLE001
            log.warning("replica_sync_disconnected", err=str(exc), backoff=backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)
