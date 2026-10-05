"""Ежедневная загрузка курсов НБРК (D-15).

10:30 по Asia/Almaty, каждый день: НБРК публикует курс на завтра днём, а
утром уже нужен курс на сегодня; выходные не исключены — курс на субботу и
воскресенье НБРК тоже выставляет. Недоступный API — предусмотренная
деградация: задача пишет ``fallback(expected=True)``, ФД вводит курс вручную.
"""
from django.db import migrations

TASK_NAME = "refdata.load_nbrk_rates"


def create_periodic_task(apps, schema_editor):
    CrontabSchedule = apps.get_model("django_celery_beat", "CrontabSchedule")
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")

    schedule, _ = CrontabSchedule.objects.get_or_create(
        minute="30", hour="10", day_of_week="*",
        day_of_month="*", month_of_year="*",
        timezone="Asia/Almaty",
    )
    PeriodicTask.objects.update_or_create(
        name=TASK_NAME,
        defaults={
            "task": "apps.refdata.tasks.load_nbrk_rates",
            "crontab": schedule,
            "enabled": True,
            "description": (
                "Курсы НБРК на сегодня (10:30 Asia/Almaty); недоступный API — "
                "ручной ввод ФД."
            ),
        },
    )


def remove_periodic_task(apps, schema_editor):
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    PeriodicTask.objects.filter(name=TASK_NAME).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("refdata", "0002_seed"),
        ("django_celery_beat", "__latest__"),
    ]

    operations = [migrations.RunPython(create_periodic_task, remove_periodic_task)]
