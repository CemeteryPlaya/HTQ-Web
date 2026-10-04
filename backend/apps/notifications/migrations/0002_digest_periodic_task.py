"""Ежедневная сводка ожидающих решений пользователям (D-23, Q-B21, Q-B30).

09:00 по Asia/Almaty, Пн–Пт — тот же ритм, что у бизнес-сводки
``core/0005``, но это другая сводка: та идёт в Telegram-чат руководства,
эта — каждому пользователю в центр уведомлений («что ждёт вашего
решения»). Нумерация дней недели cron'овская (0 = воскресенье).
"""
from django.db import migrations

TASK_NAME = "notifications.send_daily_digest"


def create_periodic_task(apps, schema_editor):
    CrontabSchedule = apps.get_model("django_celery_beat", "CrontabSchedule")
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")

    schedule, _ = CrontabSchedule.objects.get_or_create(
        minute="0", hour="9", day_of_week="1-5",
        day_of_month="*", month_of_year="*",
        timezone="Asia/Almaty",
    )
    PeriodicTask.objects.update_or_create(
        name=TASK_NAME,
        defaults={
            "task": "apps.notifications.tasks.send_daily_digest",
            "crontab": schedule,
            "enabled": True,
            "description": (
                "Сводка «ждут вашего решения» каждому пользователю в центр "
                "уведомлений (09:00 Asia/Almaty, Пн-Пт). Источники регистрируют "
                "аппки; пустой список — сообщения нет."
            ),
        },
    )


def remove_periodic_task(apps, schema_editor):
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    PeriodicTask.objects.filter(name=TASK_NAME).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("notifications", "0001_initial"),
        ("django_celery_beat", "__latest__"),
    ]

    operations = [migrations.RunPython(create_periodic_task, remove_periodic_task)]
