"""One-off: backfill Employee identity from user-service.

Run manually after deploying the identity-sync change:

    python -m app.scripts.backfill_identity

Idempotent — only changed rows are written; safe to re-run and safe to run
while the live ``user.upserted`` loop is active (both use ``_apply_user_event``).
"""

from __future__ import annotations

import asyncio
import datetime as _dt

import httpx
import jwt as _jwt
import structlog
from sqlalchemy import select

from app.core.settings import settings
from app.db import async_session_factory
from app.models.employee import Employee
from app.workers.user_identity_sync import _apply_user_event

log = structlog.get_logger(__name__)


def _admin_token() -> str:
    now = _dt.datetime.now(_dt.timezone.utc)
    return _jwt.encode(
        {
            "user_id": 0,
            "username": "hr-backfill",
            "email": "",
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


async def _fetch_users() -> dict[int, dict]:
    base = getattr(settings, "user_service_url", "http://user-service:8005")
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{base}/api/users/v1/admin/users/",
            headers={"Authorization": f"Bearer {_admin_token()}"},
        )
        resp.raise_for_status()
    payload = resp.json()
    items = payload if isinstance(payload, list) else payload.get("items", [])
    return {u["id"]: u for u in items if isinstance(u.get("id"), int)}


async def main() -> None:
    users = await _fetch_users()
    updated = 0
    async with async_session_factory() as session:
        linked = (
            await session.execute(select(Employee).where(Employee.user_id.is_not(None)))
        ).scalars().all()
        for emp in linked:
            user = users.get(emp.user_id)
            if not user:
                continue
            if await _apply_user_event(session, {"id": emp.user_id, **user}):
                updated += 1
    log.info("hr_identity_backfill_done", linked=len(linked), updated=updated)


if __name__ == "__main__":
    asyncio.run(main())
