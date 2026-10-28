"""Расписания автоматизации досок (канбан, этап S4): команды «по сроку» — раз в
15 минут, «по расписанию» — раз в 5 минут, уборка журнала запусков — в 03:10
по Алматы. Все три — диспетчеры без компании, веером по действующим компаниям.

Data-миграция в ``public`` (``django_celery_beat`` живёт там) — перечислена в
``SHARED_EFFECT_MIGRATIONS`` (``apps/companies/services/migration_service.py``)
и в реестре ``apps/core/periodic_tasks.py::PERIODIC_TASKS``: при прогоне по
схемам компаний помечается применённой, но не выполняется, а на живом стеке
строки заводит ``ensure_periodic_tasks``. Откат строки расписаний убирает.
"""
from django.db import migrations

TASKS = (
    ("tasks.automation_due", "apps.tasks.tasks.automation_due_dispatch",
     ("interval", 15),
     "Команды досок «по сроку» (канбан S4): диспетчер без компании, веером по "
     "действующим компаниям; каждая — раз на «задачу + срок»."),
    ("tasks.automation_schedule", "apps.tasks.tasks.automation_schedule_dispatch",
     ("interval", 5),
     "Команды досок «по расписанию» (канбан S4): диспетчер без компании, веером "
     "по действующим компаниям."),
    ("tasks.automation_runs_purge", "apps.tasks.tasks.automation_runs_purge_dispatch",
     ("crontab", ("10", "3")),
     "Уборка журнала запусков автоматизации досок старше 90 дней (канбан S4): "
     "диспетчер без компании, веером по действующим компаниям."),
)


def create_periodic_tasks(apps, schema_editor):
    IntervalSchedule = apps.get_model("django_celery_beat", "IntervalSchedule")
    CrontabSchedule = apps.get_model("django_celery_beat", "CrontabSchedule")
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")

    for name, path, (kind, value), description in TASKS:
        if kind == "interval":
            schedule, _ = IntervalSchedule.objects.get_or_create(every=value, period="minutes")
            fields = {"interval": schedule}
        else:
            minute, hour = value
            schedule, _ = CrontabSchedule.objects.get_or_create(
                minute=minute, hour=hour, day_of_week="*", day_of_month="*",
                month_of_year="*", timezone="Asia/Almaty")
            fields = {"crontab": schedule}
        PeriodicTask.objects.update_or_create(
            name=name,
            defaults={"task": path, "enabled": True, "description": description, **fields},
        )


def remove_periodic_tasks(apps, schema_editor):
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    PeriodicTask.objects.filter(name__in=[name for name, *_rest in TASKS]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("tasks", "0035_automation"),
        ("django_celery_beat", "__latest__"),
    ]

    operations = [
        migrations.RunPython(create_periodic_tasks, remove_periodic_tasks),
    ]
