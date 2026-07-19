# Data migration — seeds a django-q2 Schedule row for the ported
# scheduler.py cron job (see apps/cms/tasks.py::publish_scheduled_news for
# the full port writeup, including the caveat that the ported query is
# currently a no-op against the post-004 status/scheduled_at schema).
#
# The FastAPI original ran this every minute via APScheduler
# (CronTrigger(minute="*")); django-q2's equivalent is a Schedule row with
# schedule_type=MINUTES, minutes=1, repeats=-1 (forever).

from django.db import migrations

SCHEDULE_NAME = "cms.publish_scheduled_news"
TASK_FUNC = "apps.cms.tasks.publish_scheduled_news"


def create_schedule(apps, schema_editor):
    Schedule = apps.get_model("django_q", "Schedule")
    Schedule.objects.update_or_create(
        name=SCHEDULE_NAME,
        defaults={
            "func": TASK_FUNC,
            "schedule_type": "I",  # django_q.models.Schedule.MINUTES
            "minutes": 1,
            "repeats": -1,
        },
    )


def remove_schedule(apps, schema_editor):
    Schedule = apps.get_model("django_q", "Schedule")
    Schedule.objects.filter(name=SCHEDULE_NAME).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("cms", "0001_initial"),
        ("django_q", "0019_alter_task_options_alter_ormq_key_alter_ormq_lock_and_more"),
    ]

    operations = [
        migrations.RunPython(create_schedule, remove_schedule),
    ]
