"""Register media's two ``django_celery_beat`` periodic jobs (task 3.4).

Schedules are taken verbatim from ``services/media/app/workers/scheduler.py``
(APScheduler cron jobs) — not invented:

  - ``purge_soft_deleted``:   ``CronTrigger(hour=3, minute=0)``  -> daily 03:00 UTC
  - ``cleanup_orphan_files``: ``CronTrigger(day_of_week="sun", hour=4)``
                              -> weekly, Sunday 04:00 UTC

``purge_soft_deleted`` is registered ENABLED — it does real work (reaps
soft-deleted ``FileMetadata`` rows past their grace period, see
``apps.media_files.tasks.purge_soft_deleted``'s docstring).

``cleanup_orphan_files`` is registered DISABLED. Its actor in the FastAPI
source (``services/media/app/workers/actors.py::cleanup_orphan_files``) was
never implemented — a bare "not implemented yet" log line, same no-op this
port carries forward (``apps.media_files.tasks.cleanup_orphan_files``). Same
call cms made for its own dead periodic job
(``apps.cms.tasks.publish_scheduled_news``, deliberately left unscheduled):
running a no-op job on a cron would just be noise. Here the row IS created
(unlike cms, which registered nothing at all) so the intended schedule is
on record and a future engineer who implements the real storage-enumerate
logic only has to flip ``enabled=True``, not rediscover the cron.

crontab's ``day_of_week`` uses cron numbering (0 = Sunday), matching
APScheduler's ``day_of_week="sun"``.
"""

from django.db import migrations

PURGE_TASK_NAME = "media.purge_soft_deleted"
ORPHAN_TASK_NAME = "media.cleanup_orphan_files"


def create_periodic_tasks(apps, schema_editor):
    CrontabSchedule = apps.get_model("django_celery_beat", "CrontabSchedule")
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")

    purge_schedule, _ = CrontabSchedule.objects.get_or_create(
        minute="0", hour="3", day_of_week="*", day_of_month="*", month_of_year="*",
        timezone="UTC",
    )
    PeriodicTask.objects.update_or_create(
        name=PURGE_TASK_NAME,
        defaults={
            "task": "apps.media_files.tasks.purge_soft_deleted",
            "crontab": purge_schedule,
            "enabled": True,
            "description": (
                "Ported from services/media/app/workers/scheduler.py's "
                "purge_soft_deleted cron job (hour=3, minute=0)."
            ),
        },
    )

    orphan_schedule, _ = CrontabSchedule.objects.get_or_create(
        minute="0", hour="4", day_of_week="0", day_of_month="*", month_of_year="*",
        timezone="UTC",
    )
    PeriodicTask.objects.update_or_create(
        name=ORPHAN_TASK_NAME,
        defaults={
            "task": "apps.media_files.tasks.cleanup_orphan_files",
            "crontab": orphan_schedule,
            "enabled": False,
            "description": (
                "DISABLED on purpose: the ported task is a no-op (the "
                "FastAPI source's actor was never implemented, see "
                "apps.media_files.tasks.cleanup_orphan_files's docstring). "
                "Schedule kept as documentation of intent (source: "
                "scheduler.py, CronTrigger day_of_week='sun', hour=4) — "
                "flip enabled=True once the real storage-enumerate logic "
                "lands."
            ),
        },
    )


def remove_periodic_tasks(apps, schema_editor):
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    PeriodicTask.objects.filter(name__in=[PURGE_TASK_NAME, ORPHAN_TASK_NAME]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("media_files", "0001_initial"),
        ("django_celery_beat", "__latest__"),
    ]

    operations = [
        migrations.RunPython(create_periodic_tasks, remove_periodic_tasks),
    ]
