"""Одноразовый перевод существующей базы в мультикомпанейный режим.

Все текущие данные (``hr_*``, ``tasks_*``, ``contracts_*``, ``signoff_*``)
сегодня лежат в ``public`` — их создал обычный ``manage.py migrate`` до того,
как в проекте появилось понятие компании. Эта команда одноразово сводит их в
ОДНУ компанию: расщепление на реальные юридические лица делается позже
средствами платформы (``manage.py company_create`` для НОВЫХ компаний), когда
структура устоится.

Перенос — ``ALTER TABLE ... SET SCHEMA``, а не копирование: это правка
системного каталога Postgres, данные физически не двигаются со своих
страниц на диске, поэтому команда отрабатывает мгновенно независимо от
объёма таблиц. Обратная операция (вернуть таблицу в ``public``) симметрична.

⚠️ Эксплуатационное требование, а не то, что решает код: ``ALTER TABLE ...
SET SCHEMA`` берёт ``ACCESS EXCLUSIVE`` на каждую таблицу. Если в этот момент
кто-то держит долгий запрос или открытую транзакцию по одной из тенантных
таблиц, ``ALTER TABLE`` встанет в очередь и будет ждать освобождения
блокировки — а вслед за ним встанут в очередь и все новые запросы к этой
таблице (``ACCESS EXCLUSIVE`` блокирует даже ``SELECT``). Запускать эту
команду нужно в окне обслуживания, при остановленном или тихом трафике;
таймаутом эта проблема не решается — это решение оператора, а не команды.

Состояние миграций Django (``django_migrations``) обязано переехать вместе
с таблицами, а не остаться в ``public``: иначе ``migrate_companies`` увидит
пустую схему компании и попытается создать тенантные таблицы заново поверх
уже существующих (``relation already exists``). Строки не копируются, а
именно переносятся (INSERT в схему компании + DELETE из public) — компания
должна получить состояние ЦЕЛИКОМ, а не частично: если строка миграции
осталась бы в обеих схемах, ``migrate_company`` в схеме компании увидел бы
её как уже применённую (корректно), но ``manage.py migrate`` в ``public``
тоже продолжил бы считать её применённой при отсутствующей уже таблице —
расхождение, которое всплыло бы не сразу и не здесь.

Перед первым переносом сводных представлений холдинга не существует: их
строит ``rebuild_holding_views()`` по списку ДЕЙСТВУЮЩИХ компаний
(``active_company_slugs``), а до этого bootstrap'а компаний в реестре нет
вовсе. Поэтому, в отличие от ``company_create`` и ``migrate_companies``,
здесь НЕ нужен предварительный ``drop_holding_views()``: ему нечего сносить,
а ``ALTER TABLE ... SET SCHEMA`` (в отличие от ``DROP COLUMN``/``ALTER
COLUMN TYPE``) в принципе не блокируется зависимыми представлениями —
Postgres резолвит объекты представления по OID, а не по
схема-квалифицированному имени, и продолжает работать после переноса схемы
объекта. Сама пересборка после переноса нужна: компания появилась, и её
таблицы (уже в новой схеме) обязаны быть видны сводкам.
"""

from django.apps import apps as django_apps
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from psycopg import sql

from apps.companies.models import Company, CompanyKind
from apps.companies.services import holding_views, schema_service
from htqweb.tenancy.context import schema_for


class Command(BaseCommand):
    help = ("Одноразово перенести существующие данные hr/tasks/contracts/signoff "
            "из public в схему первой компании.")

    def add_arguments(self, parser):
        parser.add_argument("--slug", required=True)
        parser.add_argument("--name", required=True)
        parser.add_argument("--kind", default=CompanyKind.HOLDING,
                            choices=[c.value for c in CompanyKind])
        parser.add_argument("--dry-run", action="store_true", dest="dry_run")

    def _tenant_tables(self) -> list[str]:
        """Таблицы тенантных аппок по факту наличия моделей, а не по имени.

        Тот же источник, которым пользуется ``holding_views.holding_models``
        и ``migration_service`` — ``settings.TENANT_APPS`` — чтобы список
        таблиц к переносу не разъезжался с тем, что считается тенантным в
        остальной платформе.
        """
        tables = []
        for label in settings.TENANT_APPS:
            for model in django_apps.get_app_config(label).get_models():
                tables.append(model._meta.db_table)
        return sorted(tables)

    def handle(self, *args, **opts):
        slug, schema = opts["slug"], schema_for(opts["slug"])
        tables = self._tenant_tables()

        if opts["dry_run"]:
            # Разведка обязана работать на ЛЮБОЙ базе, в том числе там, где
            # компания с таким slug уже существует — поэтому проверка
            # одноразовости идёт СТРОГО после этого return.
            self.stdout.write(f"Сухой прогон. Схема: {schema}")
            self.stdout.write(f"Таблиц к переносу: {len(tables)}")
            for table in tables:
                self.stdout.write(f"  {table}")
            return

        if Company.objects.filter(slug=slug).exists():
            raise CommandError(f"Компания {slug} уже существует — bootstrap одноразовый.")

        company = Company(slug=slug, name=opts["name"], kind=opts["kind"])
        try:
            # full_clean(), а не голый save(): objects.create() валидаторы
            # (в том числе SLUG_VALIDATOR) не вызывает вовсе. Делается ДО
            # открытия транзакции переноса — невалидный slug обязан упасть
            # чистым CommandError раньше любого DDL, а не голым
            # ValidationError посреди ALTER TABLE.
            company.full_clean()
        except ValidationError as exc:
            raise CommandError("; ".join(
                f"{field}: {' '.join(msgs)}" for field, msgs in exc.message_dict.items()
            ))

        # DDL в Postgres транзакционен: либо переехало ВСЁ (строка реестра,
        # схема, все таблицы, состояние миграций), либо ничего. Частичный
        # перенос — худший исход из возможных (часть боевых таблиц пропала
        # бы из public, не появившись при этом полностью в схеме компании),
        # поэтому вся операция — один transaction.atomic().
        with transaction.atomic():
            company.save()
            schema_service.create_schema(slug)

            with connection.cursor() as cur:
                for table in tables:
                    # Без IF EXISTS: список таблиц собран по фактическим
                    # моделям тенантных аппок, и отсутствие любой из них в
                    # public — это не штатный случай, который стоит тихо
                    # пропустить, а расхождение схемы БД с кодом, которое
                    # обязано остановить перенос громкой ошибкой.
                    cur.execute(
                        sql.SQL("ALTER TABLE public.{} SET SCHEMA {}").format(
                            sql.Identifier(table), sql.Identifier(schema),
                        )
                    )

                # Состояние миграций обязано переехать вместе с таблицами
                # (см. докстринг модуля) — иначе migrate_companies сочтёт
                # схему пустой и попробует создать таблицы поверх уже
                # существующих.
                cur.execute(
                    sql.SQL(
                        "CREATE TABLE {}.django_migrations "
                        "(LIKE public.django_migrations INCLUDING ALL)"
                    ).format(sql.Identifier(schema))
                )
                cur.execute(
                    sql.SQL(
                        "INSERT INTO {}.django_migrations (app, name, applied) "
                        "SELECT app, name, applied FROM public.django_migrations "
                        "WHERE app = ANY(%s)"
                    ).format(sql.Identifier(schema)),
                    [list(settings.TENANT_APPS)],
                )
                cur.execute(
                    "DELETE FROM public.django_migrations WHERE app = ANY(%s)",
                    [list(settings.TENANT_APPS)],
                )

        # Вне транзакции переноса, как и в company_create/migrate_companies:
        # DROP VIEW/CREATE VIEW — своя отдельная транзакция в
        # rebuild_holding_views. drop_holding_views() здесь не нужен — см.
        # докстринг модуля: до этого bootstrap'а представлений холдинга не
        # существует вовсе.
        holding_views.rebuild_holding_views()
        self.stdout.write(self.style.SUCCESS(
            f"Перенесено {len(tables)} таблиц в {schema}. Компания {slug} создана."
        ))
