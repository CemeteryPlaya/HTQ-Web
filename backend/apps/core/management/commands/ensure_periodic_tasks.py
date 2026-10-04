"""Завести недостающие периодические задачи тенантных аппок (реестр
``apps/core/periodic_tasks.py``).

То же самое при каждом старте делает ``manage.py migrate_shared``; команда —
для ручного прогона (стек поднят с ``RUN_MIGRATIONS=0``, проверка после
выкатки). Существующие строки не меняются — см. докстринг реестра.
"""

from django.core.management.base import BaseCommand

from apps.core.periodic_tasks import ensure_periodic_tasks


class Command(BaseCommand):
    help = ("Завести в public недостающие периодические задачи тенантных "
            "аппок (hr/tasks/signoff/bpp). Существующие не меняются.")

    def handle(self, *args, **opts):
        result = ensure_periodic_tasks(stdout=self.stdout)
        self.stdout.write(self.style.SUCCESS(
            f"Периодические задачи: заведено {len(result['created'])}, "
            f"переведено на диспетчера {len(result['repaired'])}, "
            f"оставлено как есть {len(result['kept'])}."
        ))
