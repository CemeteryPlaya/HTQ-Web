"""Register messenger's ``django_celery_beat`` periodic jobs (workers/admin
sub-task, PLAN.md §6.5 — the last messenger sub-task).

Schedules are taken verbatim from ``services/messenger/app/workers/
scheduler.py`` (APScheduler cron jobs) and ``app/core/settings.py``'s
``history_archive_cron_{day,hour,minute}``/``history_archive_timezone``
defaults — not invented:

  - ``archive_room_history``: ``CronTrigger(day_of_week="sat", hour=4,
    minute=30, timezone="Asia/Almaty")`` -> weekly, Saturday 04:30 GMT+5.
    crontab's ``day_of_week`` uses standard cron numbering (0 = Sunday, ...,
    6 = Saturday — same convention already documented in ``apps/media_files/
    migrations/0002_media_periodic_tasks.py``), so Saturday = "6".
  - ``audit_log_compaction``: ``CronTrigger(hour=3, minute=30)`` -> daily
    03:30 (source's job carries no explicit timezone -> local server time;
    same "UTC" choice ``apps/mail/migrations/0004_mail_periodic_tasks.py``
    already made for its own identically-named job).
  - ``archive_old_messages``: ``CronTrigger(hour=3, minute=15)`` -> daily
    03:15 UTC.

``archive_room_history`` and ``audit_log_compaction`` are registered ENABLED
— both do real, portable work (see ``apps.messenger.tasks``'s docstrings).

``archive_old_messages`` is registered DISABLED. Its body in the FastAPI
source is a log-only MVP stub ("MVP: только лог. TODO перенос в cold
storage") — same precedent as media's ``0002_media_periodic_tasks`` migration
for ``cleanup_orphan_files``: the row IS created (schedule kept as
documentation of intent) but disabled, since running a no-op job on a cron
would just be noise; flip ``enabled=True`` once real cold-storage archival
logic lands.
"""

from django.db import migrations

ARCHIVE_TASK_NAME = "messenger.archive_room_history"
AUDIT_TASK_NAME = "messenger.audit_log_compaction"
OLD_MESSAGES_TASK_NAME = "messenger.archive_old_messages"


def create_periodic_tasks(apps, schema_editor):
    CrontabSchedule = apps.get_model("django_celery_beat", "CrontabSchedule")
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")

    archive_schedule, _ = CrontabSchedule.objects.get_or_create(
        minute="30", hour="4", day_of_week="6", day_of_month="*", month_of_year="*",
        timezone="Asia/Almaty",
    )
    PeriodicTask.objects.update_or_create(
        name=ARCHIVE_TASK_NAME,
        defaults={
            "task": "apps.messenger.tasks.archive_room_history",
            "crontab": archive_schedule,
            "enabled": True,
            "description": (
                "Ported from services/messenger/app/workers/scheduler.py's "
                "archive_history_to_s3 cron job (Saturday 04:30 GMT+5 / "
                "Asia/Almaty)."
            ),
        },
    )

    audit_schedule, _ = CrontabSchedule.objects.get_or_create(
        minute="30", hour="3", day_of_week="*", day_of_month="*", month_of_year="*",
        timezone="UTC",
    )
    PeriodicTask.objects.update_or_create(
        name=AUDIT_TASK_NAME,
        defaults={
            "task": "apps.messenger.tasks.audit_log_compaction",
            "crontab": audit_schedule,
            "enabled": True,
            "description": (
                "Ported from services/messenger/app/workers/scheduler.py's "
                "audit_log_compaction cron job (hour=3, minute=30)."
            ),
        },
    )

    old_messages_schedule, _ = CrontabSchedule.objects.get_or_create(
        minute="15", hour="3", day_of_week="*", day_of_month="*", month_of_year="*",
        timezone="UTC",
    )
    PeriodicTask.objects.update_or_create(
        name=OLD_MESSAGES_TASK_NAME,
        defaults={
            "task": "apps.messenger.tasks.archive_old_messages",
            "crontab": old_messages_schedule,
            "enabled": False,
            "description": (
                "DISABLED on purpose: the ported task is a log-only MVP stub "
                "(the FastAPI source's own job body, see "
                "apps.messenger.tasks.archive_old_messages's docstring). "
                "Schedule kept as documentation of intent (source: "
                "scheduler.py, hour=3, minute=15) — flip enabled=True once "
                "real cold-storage archival logic lands."
            ),
        },
    )


def remove_periodic_tasks(apps, schema_editor):
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    PeriodicTask.objects.filter(
        name__in=[ARCHIVE_TASK_NAME, AUDIT_TASK_NAME, OLD_MESSAGES_TASK_NAME],
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("messenger", "0002_userkey_chatattachment"),
        ("django_celery_beat", "__latest__"),
    ]

    operations = [
        migrations.RunPython(create_periodic_tasks, remove_periodic_tasks),
    ]
