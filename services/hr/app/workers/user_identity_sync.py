"""Listen for ``user.upserted`` and propagate the user's identity to HR.

user-service is the single owner of identity (ФИО/email/phone/avatar). Each
linked ``Employee`` keeps a read-only denormalised copy for fast directory /
card / org-tree rendering. This subscriber keeps that copy in sync.

- Match an Employee by ``user_id``. No match → ignore (user has no HR record).
- Only fields present in the payload overwrite; only real changes commit.
- Unlinked employees (``user_id IS NULL``) are never touched here.
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
from app.models.employee import Employee

log = structlog.get_logger(__name__)

# Payload key -> Employee attribute.
_FIELD_MAP: dict[str, str] = {
    "first_name": "first_name",
    "last_name": "last_name",
    "email": "email",
    "phone": "phone",
    "avatar_url": "avatar_url",
}

# Employee columns that are NOT NULL — never overwrite them with None.
_REQUIRED_ATTRS = {"first_name", "last_name", "email"}


async def _apply_user_event(session: AsyncSession, payload: dict[str, Any]) -> bool:
    """Apply identity fields from ``payload`` to the matching employee.

    Returns ``True`` if a row was updated (and committed), else ``False``.
    """
    user_id = payload.get("id")
    if user_id is None:
        return False
    try:
        user_id_int = int(user_id)
    except (TypeError, ValueError):
        return False

    stmt = select(Employee).where(Employee.user_id == user_id_int)
    employee = (await session.execute(stmt)).scalar_one_or_none()
    if employee is None:
        return False

    changed = False
    for payload_key, attr in _FIELD_MAP.items():
        if payload_key not in payload:
            continue
        new_value = payload[payload_key]
        # Never set a NOT-NULL identity column to NULL.
        if new_value is None and attr in _REQUIRED_ATTRS:
            continue
        if getattr(employee, attr) != new_value:
            setattr(employee, attr, new_value)
            changed = True

    if not changed:
        return False

    await session.commit()
    log.info("hr_employee_identity_synced", user_id=user_id_int, employee_id=employee.id)
    return True


async def _handle(channel: str, raw: bytes | str) -> None:
    if channel != "user.upserted":
        return
    try:
        payload = json.loads(raw if isinstance(raw, str) else raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        log.warning("hr_user_identity_sync_bad_json", raw=str(raw)[:100])
        return

    async with async_session_factory() as session:
        try:
            await _apply_user_event(session, payload)
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            log.exception("hr_user_identity_sync_error", err=str(exc))


async def run_user_identity_sync_loop() -> None:
    """Long-running background subscriber. Reconnects on transient errors."""
    backoff = 1
    while True:
        try:
            client = aioredis.Redis.from_url(settings.redis_url)
            pubsub = client.pubsub()
            await pubsub.subscribe("user.upserted")
            log.info("hr_user_identity_sync_subscribed")
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
            log.info("hr_user_identity_sync_stopped")
            raise
        except Exception as exc:  # noqa: BLE001
            log.warning("hr_user_identity_sync_disconnected", err=str(exc), backoff=backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)
