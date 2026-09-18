"""Celery tasks for the tasks domain.

Ported from ``services/task/app/workers/`` — Dramatiq actors plus an
APScheduler process become ``@shared_task`` + ``django_celery_beat`` rows
(PLAN.md §3). Every task opens with ``require_service("tasks")``, which the
reflective meta-test ``apps/core/tests/test_invariants.py`` (Test 1) verifies
by AST rather than by string match: a disabled domain must not keep doing
background work just because its HTTP surface is gated.

``tasks`` is a tenant app (``settings.TENANT_APPS``): its tables live in a
company's own Postgres schema, not ``public``. A Celery task has no HTTP
request to inherit a company from, so ``task_deadline_reminder`` and
``calendar_event_reminder`` are ``@company_task`` and take ``company_slug``
as a named argument at the call site (``htqweb/tenancy/celery.py``). beat
does not schedule them directly — it schedules the two ``*_dispatch``
companions below, which have no company of their own and fan out one real
task per active company (docs/multi-company-tenancy-followups.md п.1).

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
from htqweb.tenancy.celery import company_dispatch_task, company_task, fan_out_to_companies

logger = logging.getLogger(__name__)


@shared_task(name="apps.tasks.tasks.task_deadline_reminder")
@company_task
def task_deadline_reminder() -> int:
    """Notify assignees of tasks due today or tomorrow.

    Ported from ``workers/scheduler.py::task_deadline_reminder`` (hourly, on
    the minute). The original enqueued a Dramatiq message per task; here the
    ``Notification`` row is written directly, which is what that message was
    always going to do.

    The verb keeps the original's ``task_due_<N>d`` shape, so the frontend's
    verb parsing is unchanged. Returns the number of notifications written —
    useful in flower and asserted by the tests.

    Called as ``task_deadline_reminder.delay(company_slug="...")`` — the
    ``@company_task`` wrapper consumes ``company_slug`` before this body
    runs and does not forward it (see ``htqweb/tenancy/celery.py``), so the
    function itself takes no arguments.
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


@shared_task(name="apps.tasks.tasks.task_deadline_reminder_dispatch")
@company_dispatch_task
def task_deadline_reminder_dispatch() -> dict:
    """Dispatcher: fan ``task_deadline_reminder`` out to every active company.

    No company of its own — reads
    ``apps.companies.interface.active_company_slugs()`` and queues one
    ``task_deadline_reminder`` per active company, ``company_slug`` as a
    named argument. Enqueue failure for one company does not stop the fan
    for the rest (``fan_out_to_companies``). This is what beat schedules now
    (``apps/tasks/migrations/0019_tasks_periodic_tasks_use_dispatchers.py``).
    """
    require_service("tasks")
    return fan_out_to_companies(task_deadline_reminder,
                                label="tasks.task_deadline_reminder_dispatch")


@shared_task(name="apps.tasks.tasks.calendar_event_reminder")
@company_task
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

    Called as ``calendar_event_reminder.delay(company_slug="...")`` — see
    ``task_deadline_reminder``'s docstring above for why the function itself
    takes no ``company_slug`` parameter.
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


@shared_task(name="apps.tasks.tasks.calendar_event_reminder_dispatch")
@company_dispatch_task
def calendar_event_reminder_dispatch() -> dict:
    """Dispatcher: fan ``calendar_event_reminder`` out to every active company.

    Same shape as ``task_deadline_reminder_dispatch`` above — see its
    docstring for the fan-out contract.
    """
    require_service("tasks")
    return fan_out_to_companies(calendar_event_reminder,
                                label="tasks.calendar_event_reminder_dispatch")
