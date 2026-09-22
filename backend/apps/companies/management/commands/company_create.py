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

from django.core.management.base import BaseCommand, CommandError

from apps.access.interface import serving_holders
from apps.companies.models import CompanyKind
from apps.companies.services import lifecycle, membership_service


class Command(BaseCommand):
    help = "Завести компанию: строка реестра, схема Postgres, миграции, представления."

    def add_arguments(self, parser):
        parser.add_argument("slug")
        parser.add_argument("--name", required=True)
        parser.add_argument("--kind", required=True, choices=[c.value for c in CompanyKind])
        parser.add_argument("--parent", help="slug вышестоящей компании")
        parser.add_argument("--country", default="")
        parser.add_argument("--subdomain", default=None,
                            help="короткий адрес компании (htq вместо hi-tech-qazaqstan)")

    def handle(self, *args, **opts):
        try:
            company = lifecycle.provision_company(
                slug=opts["slug"], name=opts["name"], kind=opts["kind"],
                parent_slug=opts["parent"], country=opts["country"],
                subdomain=opts["subdomain"],
            )
        except lifecycle.LifecycleError as exc:
            raise CommandError(exc.detail) from exc
        self.stdout.write(self.style.SUCCESS(
            f"Компания {company.slug} создана, схема "
            f"co_{company.slug.replace('-', '_')} готова."
        ))
        self._print_serving_gap(company)

    def _print_serving_gap(self, company) -> None:
        """Задача 8 блока C: разрыв «обслуживающая должность есть, членства
        нет» — только ПЕЧАТАЕТ, не заводит (решение заказчика 3: членство —
        отдельное, явное решение человека). Без родителя ``serving_holders``
        честно вернёт пустой список (у корня дерева предков нет), и вывода
        не будет вовсе — молчание здесь не подмена, а факт: разрыва нет.
        """
        holder_ids = serving_holders(company.slug)
        missing = membership_service.user_ids_missing_membership(company, holder_ids)
        if not missing:
            return
        self.stdout.write(self.style.WARNING(
            f"Держателей обслуживающих должностей вышестоящих компаний без "
            f"членства в {company.slug}: {len(missing)}. Выдать: "
            f"`manage.py company_grant --company {company.slug} --serving`."
        ))
