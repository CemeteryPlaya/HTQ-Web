"""Celery tasks for the tasks domain.

Ported from ``services/task/app/workers/`` — Dramatiq actors plus an
APScheduler process become ``@shared_task`` + ``django_celery_beat`` rows
(PLAN.md §3). Every task opens with ``require_service("tasks")``, which the
reflective meta-test ``apps/core/tests/test_invariants.py`` (Test 1) verifies
by AST rather than by string match: a disabled domain must not keep doing
background work just because its HTTP surface is gated.

What did NOT come across, and why:

* ``workers/replica_sync.py`` — kept ``task_users``/``task_departments`` in
  step with user-service and hr-service over Redis pub/sub. Decision Р2
  deletes the replicas, so the subscriber has nothing to write.
* ``workers/notify_sync.py`` — turned messenger/email pub/sub events into
  ``Notification`` rows. In the monolith the producing app calls
  ``apps.tasks.interface.push_notification`` directly (a function call, in
  the same transaction), so the bus hop is gone. The de-duplication window
  that subscriber implemented lives in ``interface.push_notification``.
* ``workers/actors.py::notification_dispatch`` — was a stub that only
  logged ("TODO: write Notification row"). The real write now happens
  inline in ``task_service``; a queue hop to do a single INSERT would be
  latency with no benefit, and reproducing a never-implemented actor would
  be porting a bug.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from celery import shared_task
from django.utils import timezone

from apps.core.services import require_service

logger = logging.getLogger(__name__)


@shared_task
def task_deadline_reminder() -> int:
    """Notify assignees of tasks due today or tomorrow.

    Ported from ``workers/scheduler.py::task_deadline_reminder`` (hourly, on
    the minute). The original enqueued a Dramatiq message per task; here the
    ``Notification`` row is written directly, which is what that message was
    always going to do.

    The verb keeps the original's ``task_due_<N>d`` shape, so the frontend's
    verb parsing is unchanged. Returns the number of notifications written —
    useful in flower and asserted by the tests.
    """
    require_service("tasks")

    from .models import Notification, Status, Task

    today = date.today()
    horizon = today + timedelta(days=1)
    due = list(Task.objects.filter(
        due_date__isnull=False, due_date__lte=horizon, is_deleted=False,
        assignee_id__isnull=False,
    ).exclude(status__in=[Status.DONE, Status.CANCELLED]))

    rows = [
        Notification(
            recipient_id=task.assignee_id, actor_id=None, task=task,
            verb=f"task_due_{(task.due_date - today).days}d",
            target_type="task", target_id=task.id,
        )
        for task in due
    ]
    Notification.objects.bulk_create(rows)
    if rows:
        logger.info("task_deadline_reminder wrote %d notifications", len(rows))
    return len(rows)


@shared_task
def calendar_event_reminder() -> int:
    """Remind participants of events starting within the next 15 minutes.

    Ported from ``workers/scheduler.py::calendar_event_reminder`` (every 5
    minutes). The original published to Redis for the messenger bot and
    de-duplicated through an in-process list of ``(event_id, user_id)``
    pairs — which silently forgot everything on restart and did not
    de-duplicate across the two scheduler processes.

    This writes a ``Notification`` row instead and de-duplicates on the
    database: a participant already holding an unread reminder for the same
    event is skipped. That survives restarts and concurrent workers, which
    the in-memory list never did.
    """
    require_service("tasks")

    from .models import CalendarEventParticipant, Notification

    now = timezone.now()
    horizon = now + timedelta(minutes=15)
    upcoming = list(
        CalendarEventParticipant.objects
        .filter(event__start_at__gte=now, event__start_at__lte=horizon,
                rsvp_status__in=("pending", "accepted"))
        .select_related("event")
    )
    if not upcoming:
        return 0

    already = set(
        Notification.objects
        .filter(target_type="calendar_event",
                target_id__in=[p.event_id for p in upcoming],
                recipient_id__in=[p.user_id for p in upcoming],
                is_read=False)
        .values_list("target_id", "recipient_id")
    )

    rows = []
    for participant in upcoming:
        if (participant.event_id, participant.user_id) in already:
            continue
        starts_in = max(0, int(
            (participant.event.start_at - now).total_seconds() // 60))
        rows.append(Notification(
            recipient_id=participant.user_id, actor_id=None,
            verb=f"calendar_event_starts_in_{starts_in}m",
            target_type="calendar_event", target_id=participant.event_id,
        ))
    Notification.objects.bulk_create(rows)
    if rows:
        logger.info("calendar_event_reminder wrote %d notifications", len(rows))
    return len(rows)
