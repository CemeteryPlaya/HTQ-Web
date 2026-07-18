"""One-shot backfill for ``chat_user_replicas``.

The messenger sync loop subscribes to Redis ``user.upserted``/``user.deactivated``
events that user-service emits on every user mutation. Users who already
existed before that subscription started were never broadcast, so their
replica rows are missing — the chat picker shows "Никого не найдено".

Run after the messenger service is up and reachable to user-service::

    docker compose exec messenger-service python -m scripts.backfill_replicas

Idempotent: each row is upserted by id, so re-running is safe.
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import logging
import os
from typing import Any

import httpx
import jwt as _jwt

from app.core.settings import settings
from app.db import async_session_factory
from app.models.domain import ChatUserReplica


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("backfill_replicas")


def _internal_jwt() -> str:
    """Mint a short-lived admin JWT to authenticate against user-service."""
    now = _dt.datetime.now(_dt.timezone.utc)
    return _jwt.encode(
        {
            "user_id": 0,
            "username": "messenger-backfill",
            "email": "messenger-backfill@internal",
            "is_staff": True,
            "is_superuser": True,
            "is_admin": True,
            "token_type": "access",
            "iat": now,
            "exp": now + _dt.timedelta(minutes=5),
            "iss": settings.jwt_issuer,
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )


async def _fetch_users() -> list[dict[str, Any]]:
    base = os.environ.get("USER_SERVICE_URL") or getattr(
        settings, "user_service_url", "http://user-service:8005"
    )
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{base}/api/users/v1/admin/users/",
            headers={"Authorization": f"Bearer {_internal_jwt()}"},
        )
    if resp.status_code != 200:
        raise RuntimeError(
            f"user-service returned {resp.status_code} for admin users list: {resp.text[:200]}"
        )
    payload = resp.json()
    return payload if isinstance(payload, list) else payload.get("items") or []


async def _upsert(users: list[dict[str, Any]]) -> int:
    written = 0
    async with async_session_factory() as session:
        for u in users:
            uid = u.get("id")
            if not isinstance(uid, int):
                continue
            existing = await session.get(ChatUserReplica, uid)
            fields = {
                "username": (u.get("username") or "").strip(),
                "first_name": (u.get("first_name") or u.get("firstName") or "").strip(),
                "last_name": (u.get("last_name") or u.get("lastName") or "").strip(),
                "avatar_url": u.get("avatar_url") or u.get("avatarUrl"),
                "is_active": str(u.get("status", "active")).lower() == "active",
            }
            if existing is None:
                session.add(ChatUserReplica(id=uid, **fields))
            else:
                for k, v in fields.items():
                    setattr(existing, k, v)
            written += 1
        await session.commit()
    return written


async def main() -> None:
    users = await _fetch_users()
    log.info("fetched %d users from user-service", len(users))
    written = await _upsert(users)
    log.info("upserted %d chat_user_replicas rows", written)


if __name__ == "__main__":
    asyncio.run(main())
