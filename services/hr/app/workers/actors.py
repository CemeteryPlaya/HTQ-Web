"""Dramatiq actors for hr-service.

Discovered by:
    dramatiq app.workers.actors

Enqueue from a route:
    from app.workers.actors import vacancy_application_notify
    vacancy_application_notify.send({"vacancy_id": v.id, "candidate_email": ...})
"""

import logging
import json

import dramatiq
import redis

from app.core.settings import settings
from app.workers import broker  # noqa: F401  ensures broker is set first

logger = logging.getLogger(__name__)

DEPARTMENT_UPSERTED_CHANNEL = "department.upserted"
DEPARTMENT_DELETED_CHANNEL = "department.deleted"
EMPLOYEE_UPSERTED_CHANNEL = "employee.upserted"
EMPLOYEE_DELETED_CHANNEL = "employee.deleted"


def _publish(channel: str, payload: dict) -> int:
    try:
        client = redis.Redis.from_url(settings.redis_url)
        n = client.publish(channel, json.dumps(payload))
        client.close()
        return int(n)
    except Exception as exc:  # noqa: BLE001
        logger.warning("redis_publish_failed channel=%s err=%s", channel, exc)
        return 0


@dramatiq.actor(max_retries=3, min_backoff=2_000, max_backoff=60_000)
def vacancy_application_notify(payload: dict) -> None:
    """Notify recruiter of a new application.

    payload: {"vacancy_id": int, "application_id": int, "candidate_email": str}
    Sends through email-service /api/email/v1/send when wired; logs locally otherwise.
    """
    if not payload.get("vacancy_id") or not payload.get("application_id"):
        logger.warning("vacancy_application_notify missing fields: %s", payload)
        return
    logger.info("vacancy_application_notify queued: %s", payload)


@dramatiq.actor(max_retries=3, min_backoff=500, max_backoff=10_000)
def department_upserted(payload: dict) -> None:
    department_id = payload.get("id")
    if not department_id:
        logger.warning("department_upserted missing id: %s", payload)
        return
    n = _publish(DEPARTMENT_UPSERTED_CHANNEL, payload)
    logger.info("department_upserted published id=%s subscribers=%d", department_id, n)


@dramatiq.actor(max_retries=3)
def department_deleted(payload: dict) -> None:
    department_id = payload.get("id")
    if not department_id:
        logger.warning("department_deleted missing id: %s", payload)
        return
    n = _publish(DEPARTMENT_DELETED_CHANNEL, {"id": department_id})
    logger.info("department_deleted published id=%s subscribers=%d", department_id, n)


@dramatiq.actor(max_retries=3, min_backoff=500, max_backoff=10_000)
def employee_upserted(payload: dict) -> None:
    employee_id = payload.get("id")
    if not employee_id:
        logger.warning("employee_upserted missing id: %s", payload)
        return
    n = _publish(EMPLOYEE_UPSERTED_CHANNEL, payload)
    logger.info("employee_upserted published id=%s subscribers=%d", employee_id, n)


@dramatiq.actor(max_retries=3)
def employee_deleted(payload: dict) -> None:
    employee_id = payload.get("id")
    if not employee_id:
        logger.warning("employee_deleted missing id: %s", payload)
        return
    n = _publish(EMPLOYEE_DELETED_CHANNEL, payload)
    logger.info("employee_deleted published id=%s subscribers=%d", employee_id, n)
