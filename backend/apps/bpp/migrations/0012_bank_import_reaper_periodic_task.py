"""Уборка потерянных разборов выписки (этап 3 A, задача 3 — A4.1): раз в
10 минут.

Диспетчер ``reap_stale_imports_dispatch`` веером по компаниям переводит в
«Ошибка загрузки» загрузки, чей разбор не закончился за 15 минут (воркер
убит пределом времени, памятью или перезапуском), отменяет их строки и
стирает копию файла (``services/bank/imports.py::reap_stale``).

Data-миграция в ``public`` (``django_celery_beat`` живёт там) — перечислена в
``SHARED_EFFECT_MIGRATIONS`` (``apps/companies/services/migration_service.py``):
при прогоне по схемам компаний помечается применённой, но не выполняется.
Откат строку расписания убирает.
"""
from django.db import migrations

TASK_NAME = "bpp.bank_import_reaper"
TASK_PATH = "apps.bpp.tasks_bank.reap_stale_imports_dispatch"


def create_periodic_task(apps, schema_editor):
    IntervalSchedule = apps.get_model("django_celery_beat", "IntervalSchedule")
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")

    schedule, _ = IntervalSchedule.objects.get_or_create(every=10, period="minutes")
    PeriodicTask.objects.update_or_create(
        name=TASK_NAME,
        defaults={
            "task": TASK_PATH,
            "interval": schedule,
            "enabled": True,
            "description": (
                "Загрузки выписок, чей разбор не закончился за 15 минут, — в «Ошибка "
                "загрузки» с отменой строк: диспетчер без компании, веером по "
                "действующим компаниям."
            ),
        },
    )


def remove_periodic_task(apps, schema_editor):
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    PeriodicTask.objects.filter(name=TASK_NAME).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("bpp", "0011_bank_imports"),
        ("django_celery_beat", "__latest__"),
    ]

    operations = [
        migrations.RunPython(create_periodic_task, remove_periodic_task),
    ]
