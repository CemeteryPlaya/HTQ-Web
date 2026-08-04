"""Периодическая сверка ящиков «платформа ↔ почтовый сервер».

Расписание — раз в час (``interval(hours=1)``). Обоснование выбора: сверка
ходит на почтовый сервер и в норме находит ноль расхождений, поэтому чаще
смысла нет; реже — и заведённый мимо платформы ящик неделю остаётся
невидимым. Аналога в ``services/email/app/workers/scheduler.py`` у этой
задачи нет: сверки в FastAPI-поколении не существовало.

Строка регистрируется ВКЛЮЧЁННОЙ, но сама задача по умолчанию ничего не
меняет — ``MAIL_RECONCILE_AUTO_APPLY=false`` (см. apps/mail/tasks.py::
reconcile_mailboxes): она считает расхождения и пишет их в лог, а применяет
решения админ из раздела «Корпоративные ящики». В окружении без подключённого
почтового сервера задача завершается отчётом ``mode="unavailable"`` и
ничего не делает.
"""
from django.db import migrations

RECONCILE_TASK_NAME = "mail.reconcile_mailboxes"


def create_periodic_task(apps, schema_editor):
    IntervalSchedule = apps.get_model("django_celery_beat", "IntervalSchedule")
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")

    schedule, _ = IntervalSchedule.objects.get_or_create(every=1, period="hours")
    PeriodicTask.objects.update_or_create(
        name=RECONCILE_TASK_NAME,
        defaults={
            "task": "apps.mail.tasks.reconcile_mailboxes",
            "interval": schedule,
            "enabled": True,
            "description": (
                "Двусторонняя сверка ProvisionedMailbox с почтовым сервером. "
                "По умолчанию только отчёт в лог (MAIL_RECONCILE_AUTO_APPLY=false)."
            ),
        },
    )


def remove_periodic_task(apps, schema_editor):
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    PeriodicTask.objects.filter(name=RECONCILE_TASK_NAME).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("mail", "0006_imap_provider"),
        ("django_celery_beat", "__latest__"),
    ]

    operations = [
        migrations.RunPython(create_periodic_task, remove_periodic_task),
    ]
