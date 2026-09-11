"""Ночная сверка кадровой копии идентичности с аккаунтами.

Раз в сутки в 03:30, а не по интервалу: проход идёт по всем связанным
сотрудникам и его цель — поймать записи мимо API, а не среагировать быстро
(быстро реагируют три синхронных триггера). Ночное окно выбрано, чтобы
уведомления о дрейфе не приходили подтверждающему посреди рабочего дня.

Заводится тем же способом, что периодика core/mail — планировщик у проекта
DatabaseScheduler, расписание живёт в БД, а не в settings.
"""
from django.db import migrations

TASK_NAME = "hr.sync_identity"


def create_periodic_task(apps, schema_editor):
    CrontabSchedule = apps.get_model("django_celery_beat", "CrontabSchedule")
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")

    schedule, _ = CrontabSchedule.objects.get_or_create(
        minute="30", hour="3", day_of_week="*", day_of_month="*", month_of_year="*",
    )
    PeriodicTask.objects.update_or_create(
        name=TASK_NAME,
        defaults={
            "task": "apps.hr.tasks.sync_identity",
            "crontab": schedule,
            "enabled": True,
            "description": (
                "Сверка кадровой копии идентичности с аккаунтами. Найденное "
                "кадровое значение оформляется заявкой ДО перезаписи копии, "
                "поэтому ничего не теряется, а сам факт дрейфа попадает в "
                "метрику htqweb_fallback_total{expected=\"false\"}."
            ),
        },
    )


def remove_periodic_task(apps, schema_editor):
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    PeriodicTask.objects.filter(name=TASK_NAME).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("hr", "0018_identityapprover_identitychangerequest_and_more"),
        ("django_celery_beat", "__latest__"),
    ]

    operations = [
        migrations.RunPython(create_periodic_task, remove_periodic_task),
    ]
