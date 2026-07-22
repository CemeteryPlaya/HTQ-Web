"""Register mail's ``django_celery_beat`` periodic jobs (webhooks+workers
sub-task, PLAN.md §6.4).

Schedules are taken verbatim from ``services/email/app/workers/scheduler.py``
(APScheduler jobs) — not invented:

  - ``imap_poll_fallback``:     ``interval(seconds=60)``
  - ``oauth_token_refresh``:    ``interval(minutes=5)``
  - ``final_purge_archived_mailboxes``: ``cron(hour=3, minute=15)``
  - ``audit_log_compaction``:   ``cron(hour=3, minute=30)``

All four are registered ENABLED — every one does real, portable work (see
``apps/mail/tasks.py``'s docstrings for exactly what each does and does not
do). ``scheduler.py``'s fifth job, ``renew_push_subscriptions``, has NO task
counterpart here (see ``apps/mail/tasks.py``'s module docstring: it needs the
per-provider push-registration driver, which was never ported) — same
principle media's ``0002_media_periodic_tasks`` migration used for a
never-implemented actor, except here there is no task AT ALL to point a
disabled ``PeriodicTask`` row at, so none is created (an ``enabled=False``
row pointing at a task path that doesn't exist would just be broken, not
"documentation of intent").
"""
from django.db import migrations

POLL_TASK_NAME = "mail.imap_poll_fallback"
OAUTH_REFRESH_TASK_NAME = "mail.oauth_token_refresh"
PURGE_TASK_NAME = "mail.final_purge_archived_mailboxes"
AUDIT_COMPACTION_TASK_NAME = "mail.audit_log_compaction"


def create_periodic_tasks(apps, schema_editor):
    IntervalSchedule = apps.get_model("django_celery_beat", "IntervalSchedule")
    CrontabSchedule = apps.get_model("django_celery_beat", "CrontabSchedule")
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")

    poll_schedule, _ = IntervalSchedule.objects.get_or_create(
        every=60, period="seconds",
    )
    PeriodicTask.objects.update_or_create(
        name=POLL_TASK_NAME,
        defaults={
            "task": "apps.mail.tasks.imap_poll_fallback",
            "interval": poll_schedule,
            "enabled": True,
            "description": (
                "Ported from services/email/app/workers/scheduler.py's "
                "imap_poll_fallback cron job (interval seconds=60)."
            ),
        },
    )

    oauth_schedule, _ = IntervalSchedule.objects.get_or_create(
        every=5, period="minutes",
    )
    PeriodicTask.objects.update_or_create(
        name=OAUTH_REFRESH_TASK_NAME,
        defaults={
            "task": "apps.mail.tasks.oauth_token_refresh",
            "interval": oauth_schedule,
            "enabled": True,
            "description": (
                "Ported from services/email/app/workers/scheduler.py's "
                "oauth_token_refresh cron job (interval minutes=5)."
            ),
        },
    )

    purge_schedule, _ = CrontabSchedule.objects.get_or_create(
        minute="15", hour="3", day_of_week="*", day_of_month="*", month_of_year="*",
        timezone="UTC",
    )
    PeriodicTask.objects.update_or_create(
        name=PURGE_TASK_NAME,
        defaults={
            "task": "apps.mail.tasks.final_purge_archived_mailboxes",
            "crontab": purge_schedule,
            "enabled": True,
            "description": (
                "Ported from services/email/app/workers/scheduler.py's "
                "final_purge_archived_mailboxes cron job (hour=3, minute=15)."
            ),
        },
    )

    audit_schedule, _ = CrontabSchedule.objects.get_or_create(
        minute="30", hour="3", day_of_week="*", day_of_month="*", month_of_year="*",
        timezone="UTC",
    )
    PeriodicTask.objects.update_or_create(
        name=AUDIT_COMPACTION_TASK_NAME,
        defaults={
            "task": "apps.mail.tasks.audit_log_compaction",
            "crontab": audit_schedule,
            "enabled": True,
            "description": (
                "Ported from services/email/app/workers/scheduler.py's "
                "audit_log_compaction cron job (hour=3, minute=30)."
            ),
        },
    )


def remove_periodic_tasks(apps, schema_editor):
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    PeriodicTask.objects.filter(
        name__in=[
            POLL_TASK_NAME, OAUTH_REFRESH_TASK_NAME, PURGE_TASK_NAME,
            AUDIT_COMPACTION_TASK_NAME,
        ],
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("mail", "0003_provisionedmailbox_remove_emailaccount_mailbox_id_and_more"),
        ("django_celery_beat", "__latest__"),
    ]

    operations = [
        migrations.RunPython(create_periodic_tasks, remove_periodic_tasks),
    ]
