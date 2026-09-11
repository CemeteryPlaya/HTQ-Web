"""Point the two tasks-domain beat jobs at their dispatchers.

``task_deadline_reminder`` and ``calendar_event_reminder`` are now
``@company_task`` (``apps/tasks/tasks.py``) — the tasks/CalendarEvent tables
they read live in a company's own schema, and a Celery task has no HTTP
request to get a company from. Calling either without ``company_slug`` now
raises ``MissingCompanyArgument`` instead of quietly running against
``public``, so beat can no longer call them directly the way
``0003_tasks_periodic_tasks`` set it up.

Solution — "dispatcher + fan-out"
(docs/multi-company-tenancy-followups.md п.1): the two ``PeriodicTask`` rows
keep their names (``tasks.task_deadline_reminder`` /
``tasks.calendar_event_reminder`` — that is what the admin and tests key on),
only ``task`` changes, to the ``*_dispatch`` companion that has no company of
its own and fans one real task out to every active company.

Like 0003, this is a data migration against ``public``
(``django_celery_beat`` lives there) — listed in ``SHARED_EFFECT_MIGRATIONS``
(``apps/companies/services/migration_service.py``): marked applied but not
executed when running migrations per company schema, or every company would
rewrite the shared schedule on its own migrate.
"""
from django.db import migrations

DEADLINE_TASK_NAME = "tasks.task_deadline_reminder"
CALENDAR_TASK_NAME = "tasks.calendar_event_reminder"

OLD_DEADLINE_PATH = "apps.tasks.tasks.task_deadline_reminder"
NEW_DEADLINE_PATH = "apps.tasks.tasks.task_deadline_reminder_dispatch"
OLD_CALENDAR_PATH = "apps.tasks.tasks.calendar_event_reminder"
NEW_CALENDAR_PATH = "apps.tasks.tasks.calendar_event_reminder_dispatch"


def point_at_dispatchers(apps, schema_editor):
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    PeriodicTask.objects.filter(name=DEADLINE_TASK_NAME).update(
        task=NEW_DEADLINE_PATH,
        description=(
            "Dispatcher: no company of its own, fans "
            "task_deadline_reminder out to every active company "
            "(company_slug as a named argument)."
        ),
    )
    PeriodicTask.objects.filter(name=CALENDAR_TASK_NAME).update(
        task=NEW_CALENDAR_PATH,
        description=(
            "Dispatcher: no company of its own, fans "
            "calendar_event_reminder out to every active company "
            "(company_slug as a named argument)."
        ),
    )


def point_at_real_tasks(apps, schema_editor):
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    PeriodicTask.objects.filter(name=DEADLINE_TASK_NAME).update(
        task=OLD_DEADLINE_PATH,
        description=(
            "Ported from services/task/app/workers/scheduler.py's "
            "task_deadline_reminder cron job (minute=0)."
        ),
    )
    PeriodicTask.objects.filter(name=CALENDAR_TASK_NAME).update(
        task=OLD_CALENDAR_PATH,
        description=(
            "Ported from services/task/app/workers/scheduler.py's "
            "calendar_event_reminder interval job (minutes=5)."
        ),
    )


class Migration(migrations.Migration):

    dependencies = [
        ("tasks", "0003_tasks_periodic_tasks"),
        ("tasks", "0018_conference_room_unique"),
    ]

    operations = [
        migrations.RunPython(point_at_dispatchers, point_at_real_tasks),
    ]
