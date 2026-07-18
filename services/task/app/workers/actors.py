"""Dramatiq actors for task-service.

Discovered by:
    dramatiq app.workers.actors

Enqueue from a route:
    from app.workers.actors import notification_dispatch
    notification_dispatch.send({"recipient_id": uid, "task_id": tid, "verb": "assigned"})
"""

import logging

import dramatiq

from app.workers import broker  # noqa: F401  ensures broker is set first

logger = logging.getLogger(__name__)


@dramatiq.actor(max_retries=5, min_backoff=1_000, max_backoff=30_000)
def notification_dispatch(payload: dict) -> None:
    """Persist a Notification row and (later) push to messenger-service for live delivery.

    payload: {"recipient_id": int, "actor_id": int|None, "task_id": int|None, "verb": str}
    """
    if not payload.get("recipient_id") or not payload.get("verb"):
        logger.warning("notification_dispatch missing fields: %s", payload)
        return
    # TODO: write Notification row + POST to messenger-service WS bridge.
    logger.info("notification_dispatch queued: %s", payload)
