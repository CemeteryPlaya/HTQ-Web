"""Register the tasks domain's two ``django_celery_beat`` periodic jobs.

Schedules are taken verbatim from ``services/task/app/workers/scheduler.py``
(APScheduler jobs), not invented:

  - ``task_deadline_reminder``:  ``cron(minute=0)``      -> hourly, on the hour
  - ``calendar_event_reminder``: ``interval(minutes=5)`` -> every 5 minutes

Both are registered ENABLED — unlike media's ``cleanup_orphan_files``, these
two were real, implemented jobs in the original and do real work here (they
write ``Notification`` rows).

``calendar_event_reminder`` was an APScheduler *interval* job; beat's crontab
has no interval form, so it is expressed as ``minute="*/5"``. That is the
same cadence with one difference worth stating: an interval job counts from
process start, a crontab fires on wall-clock multiples of five. The job
de-duplicates on the database, so the shifted phase changes nothing.
"""

from django.db import migrations

DEADLINE_TASK_NAME = "tasks.task_deadline_reminder"
CALENDAR_TASK_NAME = "tasks.calendar_event_reminder"


def create_periodic_tasks(apps, schema_editor):
    CrontabSchedule = apps.get_model("django_celery_beat", "CrontabSchedule")
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")

    hourly, _ = CrontabSchedule.objects.get_or_create(
        minute="0", hour="*", day_of_week="*", day_of_month="*",
        month_of_year="*", timezone="UTC",
    )
    PeriodicTask.objects.update_or_create(
        name=DEADLINE_TASK_NAME,
        defaults={
            "task": "apps.tasks.tasks.task_deadline_reminder",
            "crontab": hourly,
            "enabled": True,
            "description": (
                "Ported from services/task/app/workers/scheduler.py's "
                "task_deadline_reminder cron job (minute=0)."
            ),
        },
    )

    every_five, _ = CrontabSchedule.objects.get_or_create(
        minute="*/5", hour="*", day_of_week="*", day_of_month="*",
        month_of_year="*", timezone="UTC",
    )
    PeriodicTask.objects.update_or_create(
        name=CALENDAR_TASK_NAME,
        defaults={
            "task": "apps.tasks.tasks.calendar_event_reminder",
            "crontab": every_five,
            "enabled": True,
            "description": (
                "Ported from services/task/app/workers/scheduler.py's "
                "calendar_event_reminder interval job (minutes=5)."
            ),
        },
    )


def delete_periodic_tasks(apps, schema_editor):
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    PeriodicTask.objects.filter(
        name__in=[DEADLINE_TASK_NAME, CALENDAR_TASK_NAME]
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("tasks", "0002_seed_system_task_types"),
        ("django_celery_beat", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(create_periodic_tasks, delete_periodic_tasks),
    ]
