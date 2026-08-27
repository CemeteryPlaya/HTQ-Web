"""Команда заведения компании: строка реестра, схема Postgres, миграции.

Первая команда, которой оператор реально заводит компанию, поэтому порядок
шагов — не деталь реализации, а единственный безопасный способ это сделать:

1. валидация — до любых разрушающих действий;
2. строка реестра + ``create_schema`` — одной транзакцией;
3. ``drop_holding_views`` — иначе Postgres запрещает contract-миграции
   (DROP COLUMN, смену типа) по таблицам, от которых зависят сводные
   представления холдинга, и ``migrate_company`` падал бы на них ровно на
   тех компаниях, ради экспанда/контракта которых представления вообще
   существуют (см. докстринг apps.companies.services.holding_views);
4. ``migrate_company`` — уже вне открытой транзакции: DDL сотни таблиц под
   одной транзакцией держал бы блокировки весь прогон;
5. ``rebuild_holding_views`` — собрать сводки заново, уже включая новую
   компанию.

Та же пара «снести до / собрать после» и в той же мотивации уже есть в
``manage.py migrate_companies`` (задача 11) — здесь она возникает по той же
причине, а не скопирована ради единообразия.
"""

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.companies.models import Company, CompanyKind
from apps.companies.services import holding_views, migration_service, schema_service


class Command(BaseCommand):
    help = "Завести компанию: строка реестра, схема Postgres, миграции, представления."

    def add_arguments(self, parser):
        parser.add_argument("slug")
        parser.add_argument("--name", required=True)
        parser.add_argument("--kind", required=True, choices=[c.value for c in CompanyKind])
        parser.add_argument("--parent", help="slug вышестоящей компании")
        parser.add_argument("--country", default="")

    def handle(self, *args, **opts):
        slug = opts["slug"]
        if Company.objects.filter(slug=slug).exists():
            raise CommandError(f"Компания {slug} уже существует.")

        parent = None
        if opts["parent"]:
            parent = Company.objects.filter(slug=opts["parent"]).first()
            if parent is None:
                raise CommandError(f"Вышестоящая компания {opts['parent']} не найдена.")

        company = Company(slug=slug, name=opts["name"], kind=opts["kind"],
                          parent=parent, country=opts["country"])
        try:
            # full_clean(), а не просто save(): objects.create() валидаторы
            # (в том числе SLUG_VALIDATOR) не вызывает вовсе.
            company.full_clean()
        except ValidationError as exc:
            raise CommandError("; ".join(
                f"{field}: {' '.join(msgs)}" for field, msgs in exc.message_dict.items()
            ))

        # Строка реестра и схема создаются в одной транзакции, а миграции —
        # после её фиксации: DDL сотни таблиц в открытой транзакции держал бы
        # блокировки всё время прогона.
        with transaction.atomic():
            company.save()
            schema_service.create_schema(slug)

        # Снести сводки ДО прогона миграций: пока представление существует,
        # Postgres запрещает удалять столбцы его таблиц и менять их типы —
        # то есть любая contract-миграция упала бы здесь же.
        holding_views.drop_holding_views()

        try:
            migration_service.migrate_company(slug)
        except Exception:
            # Схема без таблиц опаснее её отсутствия: компания выглядела бы
            # заведённой и падала бы на первом же запросе.
            schema_service.drop_schema(slug)
            company.delete()
            # Компания уже попала в active_company_slugs (status по
            # умолчанию — ACTIVE), а представления холдинга сейчас сняты
            # шагом выше. Не пересобрать их здесь значило бы оставить
            # ДЕЙСТВУЮЩИЕ компании без сводок из-за отката ЧУЖОГО, только
            # что не состоявшегося заведения — rebuild_holding_views сам
            # читает список свежим (fresh=True) и новой компании в нём уже
            # нет, потому что строка выше её удалила.
            holding_views.rebuild_holding_views()
            raise

        holding_views.rebuild_holding_views()
        self.stdout.write(self.style.SUCCESS(
            f"Компания {slug} создана, схема co_{slug.replace('-', '_')} готова."
        ))
