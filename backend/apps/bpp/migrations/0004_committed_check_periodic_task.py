"""Ночная сверка «Задействовано» (CALC-002, Q-B05, задача B2.4): 02:30 Asia/Almaty.

Диспетчер ``committed_check_dispatch`` веером по компаниям сравнивает
SQL-агрегат с пересчётом по позициям; расхождение — ``fallback`` и алерт.

Data-миграция в ``public`` (``django_celery_beat`` живёт там) — перечислена в
``SHARED_EFFECT_MIGRATIONS`` (``apps/companies/services/migration_service.py``):
при прогоне по схемам компаний помечается применённой, но не выполняется.
Откат строку расписания убирает.
"""
from django.db import migrations

TASK_NAME = "bpp.committed_check"
TASK_PATH = "apps.bpp.tasks.committed_check_dispatch"


def create_periodic_task(apps, schema_editor):
    CrontabSchedule = apps.get_model("django_celery_beat", "CrontabSchedule")
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")

    schedule, _ = CrontabSchedule.objects.get_or_create(
        minute="30", hour="2", day_of_week="*",
        day_of_month="*", month_of_year="*",
        timezone="Asia/Almaty",
    )
    PeriodicTask.objects.update_or_create(
        name=TASK_NAME,
        defaults={
            "task": TASK_PATH,
            "crontab": schedule,
            "enabled": True,
            "description": (
                "Ночная сверка «Задействовано» по статьям бюджетов (CALC-002): "
                "агрегат против пересчёта по позициям, расхождение — алерт."
            ),
        },
    )


def remove_periodic_task(apps, schema_editor):
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    PeriodicTask.objects.filter(name=TASK_NAME).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("bpp", "0003_budget_requests"),
        ("django_celery_beat", "__latest__"),
    ]

    operations = [
        migrations.RunPython(create_periodic_task, remove_periodic_task),
    ]
