"""Прогон миграций только для общих (нетенантных) аппок.

Существует ради стартовой последовательности контейнера
(``backend/docker-entrypoint.sh``, ``RUN_MIGRATIONS=1``). До задачи 13 там
стоял голый ``manage.py migrate`` — безопасный, пока все аппки жили в
``public``. После первого ``tenancy_bootstrap`` это уже не так: строки
``django_migrations`` тенантных аппок (``hr``/``tasks``/``contracts``/
``signoff``) переехали в схему компании, а голый ``migrate`` при
``search_path = public`` (умолчание при старте процесса) увидел бы это как
«ни одной миграции не применено» и НАЧАЛ БЫ СОЗДАВАТЬ их таблицы заново, уже
пустыми, поверх места, где раньше лежали боевые данные — тот же класс
отказа, ради предотвращения которого сам ``tenancy_bootstrap`` переносит
``django_migrations`` вместе с таблицами, а не копирует.

Копирование состояния миграций вместо переноса (то есть оставить строки И в
``public``, И в схеме компании) не решает проблему, а маскирует её на один
шаг: первая же НОВАЯ миграция нетенантной аппки, зависящая от актуального
состояния графа, накатывалась бы поверх ``public``, где вперемешку лежали бы
как реальные (общие), так и фантомные (тенантные, без таблиц) записи —
``ProgrammingError`` на несуществующей таблице всё равно случился бы, просто
позже и менее предсказуемо. ``tenancy_bootstrap`` поэтому именно ПЕРЕНОСИТ
эти строки — ``public.django_migrations`` обязан говорить правду о том, что
физически лежит в ``public``.

Список общих аппок ВЫЧИСЛЯЕТСЯ из графа миграций (``MigrationLoader``), а не
перечисляется руками: новая нетенантная аппка обязана подхватиться сама, без
правки этого файла при каждом добавлении домена. ``settings.TENANT_APPS`` —
единственное место, которое нужно поддерживать в актуальном состоянии (оно и
так поддерживается — от него зависят ``migration_service`` и
``holding_views``).

Прогон миграций тенантных аппок этой командой НЕ делается ни при каких
условиях — ни разу, включая самый первый старт свежей базы: с введением
мультикомпанейности жизненный цикл ``hr``/``tasks``/``contracts``/``signoff``
целиком переехал в ``manage.py tenancy_bootstrap`` (для первой компании) и
``manage.py migrate_companies`` (для всех остальных случаев) — они никогда
больше не мигрируются как часть общего ``public``.

Отсюда же — периодические задачи тенантных аппок. Их заводят data-миграции
``hr``/``tasks``/``signoff``/``bpp`` в ``django_celery_beat`` (``public``), а
эти миграции не выполняет ни эта команда (тенантные пропущены), ни
``migrate_companies`` (помечает применёнными без выполнения —
``SHARED_EFFECT_MIGRATIONS``). Поэтому после общих аппок (``django_celery_beat``
среди них, его таблицы к этому моменту есть) команда зовёт
``apps.core.periodic_tasks.ensure_periodic_tasks``: недостающие строки
расписания заводятся, существующие не трогаются.
"""

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import connection
from django.db.migrations.loader import MigrationLoader

from apps.core.periodic_tasks import ensure_periodic_tasks


class Command(BaseCommand):
    help = ("Прогнать migrate только для нетенантных аппок. Тенантные "
            "(hr/tasks/contracts/signoff) не трогает никогда — для них "
            "manage.py tenancy_bootstrap / manage.py migrate_companies.")

    def handle(self, *args, **opts):
        tenant_apps = frozenset(settings.TENANT_APPS)
        # ignore_no_migrations=True — тот же режим, что использует штатная
        # migrate: аппка без каталога migrations не должна валить загрузку
        # графа, она просто не попадёт в migrated_apps.
        loader = MigrationLoader(connection, ignore_no_migrations=True)
        shared_apps = sorted(
            app_label for app_label in loader.migrated_apps
            if app_label not in tenant_apps
        )

        for app_label in shared_apps:
            call_command("migrate", app_label, "--noinput", "--skip-checks")

        self.stdout.write(self.style.SUCCESS(
            f"Смигрировано общих аппок: {len(shared_apps)}. Тенантные "
            f"({', '.join(sorted(tenant_apps))}) пропущены — для них "
            "manage.py migrate_companies."
        ))

        periodic = ensure_periodic_tasks(stdout=self.stdout)
        self.stdout.write(self.style.SUCCESS(
            f"Периодические задачи тенантных аппок: заведено "
            f"{len(periodic['created'])}, переведено на диспетчера "
            f"{len(periodic['repaired'])}, уже были "
            f"{len(periodic['kept'])}."
        ))
