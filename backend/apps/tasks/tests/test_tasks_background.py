"""Celery tasks and the domain's public ``interface``.

The reflective meta-test already proves each ``@shared_task`` opens with
``require_service``; these tests cover what it does *behaviourally* — that a
disabled domain actually refuses the work, and that the ported jobs write
what the originals enqueued.
"""

import datetime as dt

import pytest
from django.utils import timezone

from apps.core.models import ServiceStatus
from apps.core.services import ServiceDisabled
from apps.tasks import interface, tasks as celery_tasks
from apps.tasks.models import (
    CalendarEvent, CalendarEventParticipant, Notification, Status, Task,
)


def _mk_task(**over) -> Task:
    fields = {"key": f"TASK-{Task.objects.count() + 1}", "summary": "S"}
    fields.update(over)
    return Task.objects.create(**fields)


def _disable_tasks():
    ServiceStatus.objects.update_or_create(app_label="tasks",
                                           defaults={"enabled": False})


# ── deadline reminder ───────────────────────────────────────────────────

@pytest.mark.django_db
def test_deadline_reminder_notifies_assignees_due_today_and_tomorrow():
    today = dt.date.today()
    due_today = _mk_task(due_date=today, assignee_id=11)
    due_tomorrow = _mk_task(due_date=today + dt.timedelta(days=1),
                            assignee_id=12)
    _mk_task(due_date=today + dt.timedelta(days=5), assignee_id=13)   # later

    assert celery_tasks.task_deadline_reminder() == 2
    verbs = dict(Notification.objects.values_list("recipient_id", "verb"))
    assert verbs[11] == "task_due_0d"
    assert verbs[12] == "task_due_1d"
    assert 13 not in verbs
    assert set(Notification.objects.values_list("task_id", flat=True)) == {
        due_today.id, due_tomorrow.id}


@pytest.mark.django_db
def test_deadline_reminder_skips_closed_deleted_and_unassigned():
    today = dt.date.today()
    _mk_task(due_date=today, assignee_id=11, status=Status.DONE)
    _mk_task(due_date=today, assignee_id=12, status=Status.CANCELLED)
    _mk_task(due_date=today, assignee_id=13, is_deleted=True)
    _mk_task(due_date=today, assignee_id=None)
    assert celery_tasks.task_deadline_reminder() == 0


@pytest.mark.django_db
def test_deadline_reminder_refuses_to_run_when_the_service_is_off():
    """A gated HTTP surface is not enough — background work must stop too."""
    _mk_task(due_date=dt.date.today(), assignee_id=11)
    _disable_tasks()
    with pytest.raises(ServiceDisabled):
        celery_tasks.task_deadline_reminder()
    assert Notification.objects.count() == 0


# ── calendar reminder ───────────────────────────────────────────────────

def _upcoming_event(minutes: int) -> CalendarEvent:
    start = timezone.now() + dt.timedelta(minutes=minutes)
    return CalendarEvent.objects.create(
        title="Планёрка", start_at=start, end_at=start + dt.timedelta(hours=1))


@pytest.mark.django_db
def test_calendar_reminder_notifies_participants_in_the_window():
    soon = _upcoming_event(10)
    later = _upcoming_event(90)
    CalendarEventParticipant.objects.create(event=soon, user_id=11,
                                            rsvp_status="accepted")
    CalendarEventParticipant.objects.create(event=soon, user_id=12,
                                            rsvp_status="pending")
    CalendarEventParticipant.objects.create(event=soon, user_id=13,
                                            rsvp_status="declined")
    CalendarEventParticipant.objects.create(event=later, user_id=14,
                                            rsvp_status="accepted")

    assert celery_tasks.calendar_event_reminder() == 2
    recipients = set(Notification.objects.values_list("recipient_id", flat=True))
    assert recipients == {11, 12}          # declined and out-of-window skipped
    row = Notification.objects.get(recipient_id=11)
    assert row.target_type == "calendar_event"
    assert row.target_id == soon.id
    assert row.verb.startswith("calendar_event_starts_in_")


@pytest.mark.django_db
def test_calendar_reminder_deduplicates_across_runs():
    """The original de-duplicated in a process-local list, so a restart or a
    second worker re-spammed everyone. This does it on the database."""
    event = _upcoming_event(10)
    CalendarEventParticipant.objects.create(event=event, user_id=11,
                                            rsvp_status="accepted")
    assert celery_tasks.calendar_event_reminder() == 1
    assert celery_tasks.calendar_event_reminder() == 0
    assert Notification.objects.count() == 1


@pytest.mark.django_db
def test_calendar_reminder_re_notifies_once_the_first_was_read():
    event = _upcoming_event(10)
    CalendarEventParticipant.objects.create(event=event, user_id=11,
                                            rsvp_status="accepted")
    celery_tasks.calendar_event_reminder()
    Notification.objects.update(is_read=True)
    assert celery_tasks.calendar_event_reminder() == 1


@pytest.mark.django_db
def test_calendar_reminder_refuses_to_run_when_the_service_is_off():
    _disable_tasks()
    with pytest.raises(ServiceDisabled):
        celery_tasks.calendar_event_reminder()


# ── periodic registration ───────────────────────────────────────────────

@pytest.mark.django_db
def test_both_jobs_are_registered_in_beat():
    from django_celery_beat.models import PeriodicTask

    jobs = {row.name: row for row in PeriodicTask.objects.filter(
        name__startswith="tasks.")}
    assert set(jobs) == {"tasks.task_deadline_reminder",
                         "tasks.calendar_event_reminder"}
    assert all(row.enabled for row in jobs.values())
    # Schedules carried over from the APScheduler originals.
    assert jobs["tasks.task_deadline_reminder"].crontab.minute == "0"
    assert jobs["tasks.calendar_event_reminder"].crontab.minute == "*/5"


# ── interface ───────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_get_task_brief_shape():
    task = _mk_task(assignee_id=11, department_id=3)
    brief = interface.get_task_brief(task.id)
    assert brief == {"id": task.id, "key": task.key, "summary": task.summary,
                     "status": Status.TODO, "assignee_id": 11,
                     "department_id": 3}


@pytest.mark.django_db
def test_get_task_brief_hides_soft_deleted_and_unknown():
    deleted = _mk_task(is_deleted=True)
    assert interface.get_task_brief(deleted.id) is None
    assert interface.get_task_brief(999) is None


@pytest.mark.django_db
def test_get_tasks_brief_is_batched_and_omits_unknown_ids():
    """The query count must not grow with the number of ids — that is the
    whole difference between a bulk brief and a loop of single ones. Asserted
    as "same cost for 2 ids as for 6" rather than a fixed number, because the
    service gate issues its own (cached) lookup first."""
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    tasks = [_mk_task() for _ in range(6)]

    # Warm the service-gate cache first: its ServiceStatus lookup is cached
    # with a short TTL, so an unwarmed first call carries one extra query and
    # would make the two measurements incomparable.
    interface.get_tasks_brief([])

    with CaptureQueriesContext(connection) as few:
        rows = interface.get_tasks_brief([tasks[0].id, tasks[1].id, 999])
    assert {row["id"] for row in rows} == {tasks[0].id, tasks[1].id}

    with CaptureQueriesContext(connection) as many:
        assert len(interface.get_tasks_brief([t.id for t in tasks])) == 6

    assert len(many.captured_queries) == len(few.captured_queries)


@pytest.mark.django_db
def test_push_notification_creates_a_row():
    created = interface.push_notification(
        recipient_id=11, verb="chat_message", actor_id=12,
        actor_avatar_url="https://a/1.png", target_type="chat", target_id=5)
    assert created["recipient_id"] == 11
    row = Notification.objects.get(pk=created["id"])
    assert row.actor_avatar_url == "https://a/1.png"


@pytest.mark.django_db
def test_push_notification_deduplicates_within_the_window():
    """Carried over from notify_sync's window: a redelivered event must not
    double up in the bell."""
    kwargs = dict(recipient_id=11, verb="chat_message", actor_id=12,
                  target_type="chat", target_id=5)
    assert interface.push_notification(**kwargs) is not None
    assert interface.push_notification(**kwargs) is None
    assert Notification.objects.count() == 1


@pytest.mark.django_db
def test_push_notification_lets_a_different_target_through():
    interface.push_notification(recipient_id=11, verb="chat_message",
                                target_type="chat", target_id=5)
    assert interface.push_notification(recipient_id=11, verb="chat_message",
                                       target_type="chat",
                                       target_id=6) is not None


@pytest.mark.django_db
def test_push_notification_allows_a_repeat_outside_the_window():
    kwargs = dict(recipient_id=11, verb="chat_message", target_type="chat",
                  target_id=5)
    first = interface.push_notification(**kwargs)
    Notification.objects.filter(pk=first["id"]).update(
        created_at=timezone.now() - dt.timedelta(minutes=10))
    assert interface.push_notification(**kwargs) is not None


@pytest.mark.django_db
@pytest.mark.parametrize("call", [
    lambda: interface.get_task_brief(1),
    lambda: interface.get_tasks_brief([1]),
    lambda: interface.push_notification(recipient_id=1, verb="v"),
])
def test_interface_refuses_when_the_service_is_off(call):
    _disable_tasks()
    with pytest.raises(ServiceDisabled):
        call()
