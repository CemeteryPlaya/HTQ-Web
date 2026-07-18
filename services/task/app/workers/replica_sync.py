"""User-replica sync for task-service.

Subscribes to user-service and hr-service channels and writes into local
task-service replica tables.
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
from app.models.department_replica import Department as DepartmentReplica
from app.models.user_replica import User as UserReplica


log = structlog.get_logger(__name__)


async def _upsert_user_replica(session: AsyncSession, payload: dict[str, Any]) -> None:
    user_id = int(payload["id"])
    existing = await session.get(UserReplica, user_id)
    fields = {
        "username": payload.get("username") or "",
        "email": payload.get("email") or "",
        "first_name": payload.get("first_name") or "",
        "last_name": payload.get("last_name") or "",
        # Always pull avatar_url so a deletion (None) propagates here too,
        # matching the user.avatar_url state on the source of truth.
        "avatar_url": payload.get("avatar_url"),
        "is_active": bool(payload.get("is_active", True)),
    }
    if "department_id" in payload:
        fields["department_id"] = payload.get("department_id")
    if existing is not None:
        for k, v in fields.items():
            setattr(existing, k, v)
    else:
        session.add(UserReplica(id=user_id, **fields))
    await session.commit()


async def _deactivate_replica(session: AsyncSession, user_id: int) -> None:
    existing = await session.get(UserReplica, user_id)
    if existing is None:
        return
    existing.is_active = False
    await session.commit()


async def _upsert_department_replica(session: AsyncSession, payload: dict[str, Any]) -> None:
    department_id = int(payload["id"])
    existing = await session.get(DepartmentReplica, department_id)
    fields = {"name": payload.get("name") or ""}
    if existing is not None:
        for key, value in fields.items():
            setattr(existing, key, value)
    else:
        session.add(DepartmentReplica(id=department_id, **fields))
    await session.commit()


async def _delete_department_replica(session: AsyncSession, department_id: int) -> None:
    existing = await session.get(DepartmentReplica, department_id)
    if existing is None:
        return
    await session.delete(existing)
    await session.commit()


async def _upsert_employee_scope(session: AsyncSession, payload: dict[str, Any]) -> None:
    user_id = payload.get("user_id")
    if not user_id:
        return
    existing = await session.get(UserReplica, int(user_id))
    fields = {
        "username": payload.get("username") or payload.get("email") or f"user-{user_id}",
        "email": payload.get("email") or "",
        "first_name": payload.get("first_name") or "",
        "last_name": payload.get("last_name") or "",
        "department_id": payload.get("department_id"),
        "is_active": payload.get("status", "active") == "active",
    }
    if existing is not None:
        for key, value in fields.items():
            setattr(existing, key, value)
    else:
        session.add(UserReplica(id=int(user_id), **fields))
    await session.commit()


async def _clear_employee_scope(session: AsyncSession, payload: dict[str, Any]) -> None:
    user_id = payload.get("user_id")
    if not user_id:
        return
    existing = await session.get(UserReplica, int(user_id))
    if existing is None:
        return
    existing.department_id = None
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
                await _deactivate_replica(session, int(payload.get("id", 0)))
            elif channel == "department.upserted":
                await _upsert_department_replica(session, payload)
            elif channel == "department.deleted":
                await _delete_department_replica(session, int(payload.get("id", 0)))
            elif channel == "employee.upserted":
                await _upsert_employee_scope(session, payload)
            elif channel == "employee.deleted":
                await _clear_employee_scope(session, payload)
            else:
                return
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            log.exception("replica_sync_error", channel=channel, err=str(exc))
            return

    log.info("replica_synced", channel=channel, user_id=payload.get("id"))


async def run_user_replica_sync_loop() -> None:
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
                "employee.upserted",
                "employee.deleted",
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
