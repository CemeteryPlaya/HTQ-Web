"""Replica sync for requests-service.

Subscribes to user-service and hr-service Redis channels and keeps local
``request_users`` / ``request_departments`` replicas current. Mirrors the
task-service pattern (services/task/app/workers/replica_sync.py).
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any

import redis.asyncio as aioredis
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import settings
from app.db import async_session_factory
from app.models.department_replica import RequestDepartment
from app.models.user_replica import RequestUser


log = structlog.get_logger(__name__)


async def _upsert_user_replica(session: AsyncSession, payload: dict[str, Any]) -> None:
    user_id = int(payload["id"])
    existing = await session.get(RequestUser, user_id)
    fields = {
        "username": payload.get("username") or "",
        "email": payload.get("email") or "",
        "first_name": payload.get("first_name") or "",
        "last_name": payload.get("last_name") or "",
        "is_active": bool(payload.get("is_active", True)),
        "is_elevated": bool(payload.get("is_elevated", False)),
    }
    if existing is not None:
        for k, v in fields.items():
            setattr(existing, k, v)
    else:
        session.add(RequestUser(id=user_id, **fields))
    await session.commit()


async def _deactivate_user_replica(session: AsyncSession, user_id: int) -> None:
    existing = await session.get(RequestUser, user_id)
    if existing is not None:
        existing.is_active = False
        existing.deactivated_at = datetime.now(timezone.utc)
    # Auto-skip every live approval slot this user holds + advance the
    # affected requests. Import here to avoid a circular import at module load
    # (request_runtime imports models which import workers).
    try:
        from app.services.request_runtime import handle_user_deactivated
        touched = await handle_user_deactivated(session, user_id)
        if touched:
            log.info("replica_sync_deactivation_advanced", user_id=user_id, requests=touched)
    except Exception as exc:  # noqa: BLE001
        log.exception("replica_sync_deactivation_advance_failed", user_id=user_id, err=str(exc))
        # The replica row still needs to be flagged as deactivated even if the
        # advance loop failed — fall through to commit.
    await session.commit()


async def _upsert_department_replica(session: AsyncSession, payload: dict[str, Any]) -> None:
    dept_id = int(payload["id"])
    existing = await session.get(RequestDepartment, dept_id)
    fields = {
        "name": payload.get("name") or "",
        "parent_id": payload.get("parent_id"),
        "head_user_id": payload.get("head_user_id"),
    }
    if existing is not None:
        for k, v in fields.items():
            setattr(existing, k, v)
    else:
        session.add(RequestDepartment(id=dept_id, **fields))
    await session.commit()


async def _delete_department_replica(session: AsyncSession, dept_id: int) -> None:
    existing = await session.get(RequestDepartment, dept_id)
    if existing is None:
        return
    await session.delete(existing)
    await session.commit()


async def _handle(channel: str, raw: bytes | str) -> None:
    try:
        payload = json.loads(raw if isinstance(raw, str) else raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        log.warning("replica_sync_bad_json", channel=channel)
        return

    async with async_session_factory() as session:
        try:
            if channel == "user.upserted":
                await _upsert_user_replica(session, payload)
            elif channel == "user.deactivated":
                await _deactivate_user_replica(session, int(payload.get("id", 0)))
            elif channel == "department.upserted":
                await _upsert_department_replica(session, payload)
            elif channel == "department.deleted":
                await _delete_department_replica(session, int(payload.get("id", 0)))
            else:
                return
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            log.exception("replica_sync_error", channel=channel, err=str(exc))
            return

    log.info("replica_synced", channel=channel, entity_id=payload.get("id"))


async def run_replica_sync_loop() -> None:
    backoff = 1
    while True:
        try:
            client = aioredis.Redis.from_url(settings.redis_url)
            pubsub = client.pubsub()
            channels = [
                "user.upserted",
                "user.deactivated",
                "department.upserted",
                "department.deleted",
            ]
            await pubsub.subscribe(*channels)
            log.info("replica_sync_subscribed", channels=channels)
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
