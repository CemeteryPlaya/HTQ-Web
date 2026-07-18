"""Dramatiq actors for user-service.

Discovered by the worker entrypoint:
    dramatiq app.workers.actors

Enqueue from a route:
    from app.workers.actors import email_confirmation_send
    email_confirmation_send.send({"to": user.email, "token": token})
"""

import json
import logging

import dramatiq
import redis

from app.core.settings import settings
from app.workers import broker  # noqa: F401  ensures broker is set first

logger = logging.getLogger(__name__)


# Redis pub/sub channels for cross-service user replica updates.
# Subscribed by messenger-service (ChatUserReplica) and task-service
# (task.users), see services/<svc>/app/workers/replica_sync.py.
USER_UPSERTED_CHANNEL = "user.upserted"
USER_DEACTIVATED_CHANNEL = "user.deactivated"
USER_DELETED_CHANNEL = "user.deleted"


def _publish(channel: str, payload: dict) -> int:
    """Publish a JSON message to a Redis pub/sub channel.

    Returns the number of subscribers that received it. Errors are logged but
    not raised so an inability to publish a notification never blocks the
    primary user-service operation that triggered it.
    """
    try:
        client = redis.Redis.from_url(settings.redis_url)
        n = client.publish(channel, json.dumps(payload))
        client.close()
        return int(n)
    except Exception as exc:  # noqa: BLE001
        logger.warning("redis_publish_failed channel=%s err=%s", channel, exc)
        return 0


@dramatiq.actor(max_retries=5, min_backoff=1_000, max_backoff=60_000)
def email_confirmation_send(payload: dict) -> None:
    """Send a registration-confirmation email.

    payload: {"to": str, "token": str, "display_name": str | None}
    Real SMTP/transactional-email integration is wired by the email-service;
    here we hand the message off via HTTP or log it during local dev.
    """
    to = payload.get("to")
    token = payload.get("token")
    if not to or not token:
        logger.warning("email_confirmation_send missing fields: %s", payload)
        return
    # TODO: POST to email-service /api/email/v1/send when that service lands.
    logger.info("email_confirmation_send queued for %s", to)


@dramatiq.actor(max_retries=3, min_backoff=500, max_backoff=10_000)
def user_upserted(payload: dict) -> None:
    """Broadcast a `user.upserted` event for downstream replicas.

    Called from auth/registration/admin handlers right after a user row is
    created or updated. Payload shape (matches ChatUserReplica + task.users
    column subset, plus is_active flag derived from status):

        {
          "id": int,
          "username": str,
          "email": str,
          "first_name": str,
          "last_name": str,
          "display_name": str,
          "avatar_url": str | None,
          "status": "active" | "pending" | "suspended" | "rejected",
          "is_active": bool,
        }
    """
    user_id = payload.get("id")
    if not user_id:
        logger.warning("user_upserted missing id: %s", payload)
        return
    n = _publish(USER_UPSERTED_CHANNEL, payload)
    logger.info("user_upserted published id=%s subscribers=%d", user_id, n)


@dramatiq.actor(max_retries=3)
def user_deactivated(payload: dict) -> None:
    """Broadcast `user.deactivated` so replicas mark `is_active=False`.

    Payload: {"id": int}
    """
    user_id = payload.get("id")
    if not user_id:
        logger.warning("user_deactivated missing id: %s", payload)
        return
    n = _publish(USER_DEACTIVATED_CHANNEL, {"id": user_id})
    logger.info("user_deactivated published id=%s subscribers=%d", user_id, n)


@dramatiq.actor(max_retries=3)
def user_deleted(payload: dict) -> None:
    """Broadcast `user.deleted` so downstream services start the cascade.

    Payload: ``{"id": int, "email": str | None, "deleted_at": str (iso)}``

    Email-service uses this to flag the user's mailbox as eligible for
    final purge after the retention window.
    """
    user_id = payload.get("id")
    if not user_id:
        logger.warning("user_deleted missing id: %s", payload)
        return
    n = _publish(USER_DELETED_CHANNEL, payload)
    logger.info("user_deleted published id=%s subscribers=%d", user_id, n)


@dramatiq.actor(max_retries=1)
def rebuild_user_replicas() -> None:
    """One-shot bootstrap: re-publish every active user as `user.upserted`.

    Run after deploying replica-sync to a service that didn't have it before,
    or to reseed a wiped replica table:

        docker compose exec user-worker python -c \\
            "from app.workers.actors import rebuild_user_replicas; rebuild_user_replicas.send()"

    Dramatiq actors are sync, but the user-service only ships the asyncpg
    driver. We bridge with `asyncio.run()` to reuse the existing async engine.
    """
    import asyncio

    from sqlalchemy import select

    from app.db import async_session_factory
    from app.models.user import User, UserStatus

    async def _stream():
        published = 0
        async with async_session_factory() as session:
            result = await session.execute(select(User).order_by(User.id))
            for user in result.scalars():
                payload = {
                    "id": user.id,
                    "username": user.username,
                    "email": user.email,
                    "first_name": user.first_name or "",
                    "last_name": user.last_name or "",
                    "display_name": user.display_name or "",
                    "avatar_url": user.avatar_url,
                    "status": user.status.value if hasattr(user.status, "value") else str(user.status),
                    "is_active": user.status == UserStatus.ACTIVE,
                }
                _publish(USER_UPSERTED_CHANNEL, payload)
                published += 1
        return published

    n = asyncio.run(_stream())
    logger.info("rebuild_user_replicas published=%d", n)
