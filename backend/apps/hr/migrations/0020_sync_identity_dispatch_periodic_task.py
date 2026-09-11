"""Перевести расписание ``hr.sync_identity`` на диспетчера.

У Celery-задачи нет HTTP-запроса, поэтому у ``sync_identity`` (теперь
``@company_task``, см. ``apps/hr/tasks.py``) нет и контекста компании: вызов
без ``company_slug`` падает ``MissingCompanyArgument``, а не молча уходит в
public. beat планировал именно ``sync_identity`` напрямую (миграция
``0019_identity_sync_periodic_task``) — с ней задача ночью падала бы на
каждый прогон.

Решение — «диспетчер + веер» (docs/multi-company-tenancy-followups.md п.1):
строка ``PeriodicTask`` не создаётся заново и не переименовывается (имя
``hr.sync_identity`` остаётся — под ним её ищут в админке и в тестах), меняется
только ``task``: теперь он указывает на ``sync_identity_dispatch``, которая
без компании читает ``active_company_slugs()`` и веером ставит
``sync_identity`` на каждую действующую компанию.

Как и 0019, это data-миграция в ``public`` (``django_celery_beat`` там и
живёт) — перечислена в ``SHARED_EFFECT_MIGRATIONS``
(``apps/companies/services/migration_service.py``): при прогоне по схемам
компаний помечается применённой, но не выполняется, иначе на каждую
компанию расписание переписывалось бы заново.
"""
from django.db import migrations

TASK_NAME = "hr.sync_identity"
OLD_TASK_PATH = "apps.hr.tasks.sync_identity"
NEW_TASK_PATH = "apps.hr.tasks.sync_identity_dispatch"


def point_at_dispatcher(apps, schema_editor):
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    PeriodicTask.objects.filter(name=TASK_NAME).update(
        task=NEW_TASK_PATH,
        description=(
            "Диспетчер сверки кадровой копии идентичности с аккаунтами: "
            "без компании, веером ставит sync_identity на каждую "
            "действующую компанию (company_slug именованным аргументом)."
        ),
    )


def point_at_real_task(apps, schema_editor):
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    PeriodicTask.objects.filter(name=TASK_NAME).update(
        task=OLD_TASK_PATH,
        description=(
            "Сверка кадровой копии идентичности с аккаунтами. Найденное "
            "кадровое значение оформляется заявкой ДО перезаписи копии, "
            "поэтому ничего не теряется, а сам факт дрейфа попадает в "
            "метрику htqweb_fallback_total{expected=\"false\"}."
        ),
    )


class Migration(migrations.Migration):

    dependencies = [
        ("hr", "0019_identity_sync_periodic_task"),
    ]

    operations = [
        migrations.RunPython(point_at_dispatcher, point_at_real_task),
    ]
