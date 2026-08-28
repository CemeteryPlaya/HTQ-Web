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

Шаги 3 и 4 — в ОДНОМ ``try``: падение любого из них означает, что схема без
таблиц (или без снесённых представлений) опаснее её отсутствия, и оба случая
обязаны откатываться одинаково.

Откат — три НЕЗАВИСИМЫХ шага (снос схемы, удаление строки реестра, пересборка
сводок), каждый обёрнут ``migration_service._cleanup``: сбой одного не должен
мешать остальным отработать и не должен подменить собой исходную причину
падения ``migrate_company`` — та же логика и тот же примитив
(``htqweb/fallback.py``, ``expected=True``), которым сам ``migration_service``
уже защищает свою собственную уборку после прогона (см. его докстринг).
Переиспользуется приватная функция соседнего модуля той же аппки, а не её
копия: это внутриаппочный импорт (``apps.companies`` -> ``apps.companies``),
инвариант межаппных границ (``apps/core/tests/test_app_isolation.py``) его не
касается, а порождать вторую реализацию того же примитива было бы обманчивым
дублированием.
"""

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import ProgrammingError, transaction

from apps.companies.models import Company, CompanyKind
from apps.companies.services import holding_views, migration_service, schema_service
from apps.companies.services.migration_service import _cleanup


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

        try:
            # Снести сводки ДО прогона миграций: пока представление
            # существует, Postgres запрещает удалять столбцы его таблиц и
            # менять их типы — то есть любая contract-миграция упала бы
            # здесь же. Сбой самого сноса (обрыв блокировки, соединения) —
            # тоже повод для отката: без него компания осталась бы активной
            # строкой реестра со схемой без единой мигрированной таблицы.
            holding_views.drop_holding_views()
            migration_service.migrate_company(slug)
        except Exception:
            # Схема без таблиц опаснее её отсутствия: компания выглядела бы
            # заведённой и падала бы на первом же запросе. Три шага ниже —
            # НЕЗАВИСИМЫЕ: падение любого (например, обрыв соединения на
            # DROP SCHEMA) не должно ни остановить остальные, ни подменить
            # собой исходную причину падения migrate_company/drop_holding_views
            # — именно поэтому они идут через _cleanup, а не голыми вызовами
            # подряд.
            _cleanup("снос схемы после отката",
                     lambda: schema_service.drop_schema(slug))
            # Компания уже попала в active_company_slugs (status по
            # умолчанию — ACTIVE), а представления холдинга сейчас сняты
            # шагом выше. Не пересобрать их здесь значило бы оставить
            # ДЕЙСТВУЮЩИЕ компании без сводок из-за отката ЧУЖОГО, только
            # что не состоявшегося заведения — rebuild_holding_views сам
            # читает список свежим (fresh=True), поэтому важно, чтобы
            # удаление строки реестра шло РАНЬШЕ пересборки.
            _cleanup("удаление строки реестра после отката", company.delete)
            _cleanup("пересборка сводок холдинга после отката",
                     holding_views.rebuild_holding_views)
            raise

        try:
            holding_views.rebuild_holding_views()
        except ProgrammingError as exc:
            # Компания X (эта) создана и мигрирована успешно — откатывать
            # её не за что. Падает СВОДКА, потому что другая, ранее
            # заведённая компания отстала по миграциям и состав столбцов
            # разошёлся; тот же сценарий и то же сообщение по духу, что и в
            # manage.py migrate_companies (задача 11).
            raise CommandError(
                f"Компания {slug} создана и мигрирована, но сводки холдинга "
                "собрать нельзя: состав столбцов разошёлся с другой "
                "компанией, отставшей по миграциям. Представления оставлены "
                "снесёнными: читатель получит громкую ошибку вместо цифр по "
                "полумигрированной группе. Доведите остальные компании — "
                f"`manage.py migrate_companies` без фильтров. Причина: {exc}"
            ) from exc

        self.stdout.write(self.style.SUCCESS(
            f"Компания {slug} создана, схема co_{slug.replace('-', '_')} готова."
        ))
