"""Утренняя сводка по бизнес-метрикам в Telegram.

09:00 по Asia/Almaty, Пн–Пт. Часовой пояс задан явно, как у
``apps/messenger/migrations/0003_messenger_periodic_tasks.py``: «утро» должно
быть утром там, где сидит компания, а не в UTC. Нумерация дней недели —
стандартная cron'овская (0 = воскресенье), та же конвенция уже зафиксирована
в ``apps/media_files/migrations/0002_media_periodic_tasks.py``.

Выходные исключены намеренно: сводка о том, что в субботу никто не работал, —
это шум, а шум в канале уведомлений стоит дороже, чем пропущенная суббота.

``enabled=True`` безопасно и на боевой БД, и на пустом стенде: без
``TELEGRAM_BOT_TOKEN``/``TELEGRAM_DIGEST_CHAT_ID`` задача молча ничего не
делает (см. ``apps/core/tasks.py::send_daily_digest``).
"""
from django.db import migrations

TASK_NAME = "core.send_daily_digest"


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
            "task": "apps.core.tasks.send_daily_digest",
            "crontab": schedule,
            "enabled": True,
            "description": (
                "Утренняя сводка по бизнес-метрикам в Telegram (09:00 "
                "Asia/Almaty, Пн-Пт). Читает готовый снимок из кэша — "
                "дополнительных запросов к БД не делает. Без TELEGRAM_* "
                "молча пропускается."
            ),
        },
    )


def remove_periodic_task(apps, schema_editor):
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    PeriodicTask.objects.filter(name=TASK_NAME).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0004_business_metrics_periodic_task"),
        ("django_celery_beat", "__latest__"),
    ]

    operations = [
        migrations.RunPython(create_periodic_task, remove_periodic_task),
    ]
