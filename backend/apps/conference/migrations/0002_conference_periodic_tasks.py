"""Периодические задачи конференций (django_celery_beat).

Три уборщика, каждый закрывает свой способ, которым конвейер записи может
оставить мусор:

* ``purge_expired`` — ретенция. Раз в сутки стирает медиа встреч старше
  ``CONFERENCE_RETENTION_DAYS`` (25 дней, решение заказчика). Единственная
  задача здесь, которая выполняет обещание, данное пользователю, а не
  чинит сбой, — поэтому она включена безусловно и её нельзя выключать
  «до выяснения».
* ``reap_orphan_sessions`` — SFU перезапустился посреди звонка и не прислал
  finish. Строка встречи осталась открытой и держит частичный уникальный
  индекс комнаты, то есть следующая встреча в той же комнате прилипнет
  к прошлой. Раз в час.
* ``sweep_orphan_raw_dirs`` — обратный сбой: дорожки на том легли, а
  сообщить о сессии SFU не смог (Django был недоступен). Такие каталоги
  никем не подобраны и растут молча. Раз в сутки, после ретенции.

Время — 03:45 и 04:15 UTC: после ночных задач media (03:00) и почты
(03:15/03:30), чтобы тяжёлые обходы хранилища не накладывались друг на друга.
"""

from django.db import migrations

PURGE_TASK = "conference.purge_expired"
REAP_TASK = "conference.reap_orphan_sessions"
SWEEP_TASK = "conference.sweep_orphan_raw_dirs"


def create_periodic_tasks(apps, schema_editor):
    CrontabSchedule = apps.get_model("django_celery_beat", "CrontabSchedule")
    IntervalSchedule = apps.get_model("django_celery_beat", "IntervalSchedule")
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")

    purge_schedule, _ = CrontabSchedule.objects.get_or_create(
        minute="45", hour="3", day_of_week="*", day_of_month="*",
        month_of_year="*", timezone="UTC",
    )
    PeriodicTask.objects.update_or_create(
        name=PURGE_TASK,
        defaults={
            "task": "apps.conference.tasks.purge_expired",
            "crontab": purge_schedule,
            "enabled": True,
            "description": (
                "Ретенция записей конференций: через CONFERENCE_RETENTION_DAYS "
                "(25) дней медиа удаляется полностью. История встречи и "
                "текстовый протокол сохраняются — стираются только байты."
            ),
        },
    )

    hourly, _ = IntervalSchedule.objects.get_or_create(every=1, period="hours")
    PeriodicTask.objects.update_or_create(
        name=REAP_TASK,
        defaults={
            "task": "apps.conference.tasks.reap_orphan_sessions",
            "interval": hourly,
            "enabled": True,
            "description": (
                "Принудительно закрывает встречи, о конце которых SFU не "
                "сообщил (перезапуск посреди звонка). Иначе строка висит "
                "открытой и занимает уникальный индекс комнаты."
            ),
        },
    )

    sweep_schedule, _ = CrontabSchedule.objects.get_or_create(
        minute="15", hour="4", day_of_week="*", day_of_month="*",
        month_of_year="*", timezone="UTC",
    )
    PeriodicTask.objects.update_or_create(
        name=SWEEP_TASK,
        defaults={
            "task": "apps.conference.tasks.sweep_orphan_raw_dirs",
            "crontab": sweep_schedule,
            "enabled": True,
            "description": (
                "Убирает с тома каталоги сырых дорожек, которым не "
                "соответствует ни одна встреча в базе."
            ),
        },
    )


def remove_periodic_tasks(apps, schema_editor):
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    PeriodicTask.objects.filter(
        name__in=[PURGE_TASK, REAP_TASK, SWEEP_TASK],
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("conference", "0001_initial"),
        ("django_celery_beat", "__latest__"),
    ]

    operations = [
        migrations.RunPython(create_periodic_tasks, remove_periodic_tasks),
    ]
