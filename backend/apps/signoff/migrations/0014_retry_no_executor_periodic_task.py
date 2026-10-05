"""Периодическая повторная попытка для этапов «Нет исполнителя» (БЗО, B1.2).

Этап ленивого маршрута без исполнителя ждёт (ТЗ §16.1 п.5). Назначили
сотрудника или временного исполнителя — каждые 15 минут диспетчер
``retry_no_executor_dispatch`` веером по компаниям ищет исполнителей заново;
не ждать можно ручкой ``POST processes/<id>/retry-executors``.

Data-миграция в ``public`` (``django_celery_beat`` живёт там) — перечислена в
``SHARED_EFFECT_MIGRATIONS`` (``apps/companies/services/migration_service.py``):
при прогоне по схемам компаний помечается применённой, но не выполняется.
Откат строку расписания убирает.
"""
from django.db import migrations

TASK_NAME = "signoff.retry_no_executor"
TASK_PATH = "apps.signoff.tasks.retry_no_executor_dispatch"


def create_periodic_task(apps, schema_editor):
    IntervalSchedule = apps.get_model("django_celery_beat", "IntervalSchedule")
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")

    schedule, _ = IntervalSchedule.objects.get_or_create(every=15, period="minutes")
    PeriodicTask.objects.update_or_create(
        name=TASK_NAME,
        defaults={
            "task": TASK_PATH,
            "interval": schedule,
            "enabled": True,
            "description": (
                "Повторный поиск исполнителей этапам «Нет исполнителя» (ТЗ §16.1 "
                "п.5): диспетчер без компании, веером по действующим компаниям."
            ),
        },
    )


def remove_periodic_task(apps, schema_editor):
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    PeriodicTask.objects.filter(name=TASK_NAME).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("signoff", "0013_route_flags"),
        ("django_celery_beat", "__latest__"),
    ]

    operations = [
        migrations.RunPython(create_periodic_task, remove_periodic_task),
    ]
