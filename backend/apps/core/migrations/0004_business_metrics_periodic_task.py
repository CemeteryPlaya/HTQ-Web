"""Периодический пересчёт бизнес-метрик (наблюдаемость).

Интервал 60 c согласован с ``CACHE_TTL = 180`` в ``apps/core/metrics.py``:
кэш переживает один пропущенный запуск, но не показывает вчерашние цифры,
если сборщик встал совсем.

Заводится тем же способом, что и периодика почты
(``apps/mail/migrations/0004_mail_periodic_tasks.py``) — планировщик у
проекта DatabaseScheduler, расписание живёт в БД, а не в settings.
"""
from django.db import migrations

TASK_NAME = "core.collect_business_metrics"


def create_periodic_task(apps, schema_editor):
    IntervalSchedule = apps.get_model("django_celery_beat", "IntervalSchedule")
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")

    schedule, _ = IntervalSchedule.objects.get_or_create(
        every=60, period="seconds",
    )
    PeriodicTask.objects.update_or_create(
        name=TASK_NAME,
        defaults={
            "task": "apps.core.tasks.collect_business_metrics",
            "interval": schedule,
            "enabled": True,
            "description": (
                "Пересчёт бизнес-метрик в кэш для /metrics. Считается здесь, "
                "а не на скрейпе: гейдж с походом в БД при четырёх воркерах "
                "gunicorn'а не работает в мультипроцессном режиме."
            ),
        },
    )


def remove_periodic_task(apps, schema_editor):
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    PeriodicTask.objects.filter(name=TASK_NAME).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0003_enable_conference"),
        ("django_celery_beat", "__latest__"),
    ]

    operations = [
        migrations.RunPython(create_periodic_task, remove_periodic_task),
    ]
