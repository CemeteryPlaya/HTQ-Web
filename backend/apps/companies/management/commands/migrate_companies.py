"""Команда прогона миграций по схемам компаний.

Тонкая обёртка над apps.companies.services.migration_service: вся логика —
там, здесь только разбор аргументов и печать. Отдельная команда, а не флаг
штатной ``migrate``, потому что ``migrate`` работает с public и знать про
схемы компаний не должна.

Здесь же живёт пара «снести сводки до, собрать после». Причина не в
удобстве: пока представление схемы holding существует, Postgres запрещает
удалять столбцы его таблиц и менять их типы, то есть ЛЮБАЯ contract-миграция
по сводимой модели падает на каждой компании (см. докстринг
apps.companies.services.holding_views). Место именно здесь, а не в
migration_service.migrate_company: та работает по ОДНОЙ компании и внутри
advisory-lock'а, а снос и пересборка нужны по одному разу на весь прогон.
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import ProgrammingError

from apps.companies.interface import active_company_slugs
from apps.companies.models import Company
from apps.companies.services import holding_views, migration_service


class Command(BaseCommand):
    help = ("Довести схемы компаний до текущей версии миграций. "
            "Без --company обрабатывает все действующие компании.")

    def add_arguments(self, parser):
        parser.add_argument("--company", help="slug одной компании")
        parser.add_argument("--app",
                            help="только эта аппка (hr/tasks/contracts/signoff)")
        parser.add_argument(
            "--to",
            help="довести аппку до этой миграции, напр. 0042_x. Только "
                 "ВПЕРЁД: откат схемы компании запрещён")
        parser.add_argument("--plan", action="store_true",
                            help="сухой прогон: показать, что применилось бы")

    def handle(self, *args, **opts):
        # fresh=True: команду запускают сразу после заведения компании, а
        # пятисекундный кэш списка отдал бы её без этой самой компании —
        # схема осталась бы пустой молча, без ошибки и следа в логе.
        slugs = ([opts["company"]] if opts["company"]
                 else active_company_slugs(fresh=True))
        if not slugs:
            raise CommandError("Нет действующих компаний.")

        # Проверка ДО сноса представлений, а не только внутри цикла: после
        # сноса холдинг остаётся без сводок до успешной пересборки, и
        # ронять их из-за опечатки в аргументе незачем.
        known = set(Company.objects.filter(slug__in=slugs)
                    .values_list("slug", flat=True))
        missing = sorted(set(slugs) - known)
        if missing:
            raise CommandError(
                "Нет в реестре: " + ", ".join(repr(s) for s in missing) + ".")

        # Сухой прогон ничего не меняет — ронять ради него сводки нельзя.
        dry_run = opts["plan"]
        if not dry_run:
            dropped = holding_views.drop_holding_views()
            if dropped:
                self.stdout.write(
                    f"Сводки холдинга сняты на время прогона: {len(dropped)} шт."
                )

        for slug in slugs:
            try:
                result = migration_service.migrate_company(
                    slug, app_label=opts["app"], target=opts["to"],
                    plan=dry_run,
                )
            except Company.DoesNotExist as exc:
                raise CommandError(f"Компании {slug!r} нет в реестре.") from exc
            except (ValueError,
                    migration_service.SchemaMissing,
                    migration_service.BackwardsMigrationRefused) as exc:
                # Опечатка в аргументе или незаведённая схема — это работа
                # для оператора, а не трассировка на пол-экрана. Ошибка самой
                # миграции, наоборот, летит наверх целиком: там нужен
                # traceback.
                raise CommandError(str(exc)) from exc

            if dry_run:
                pending = result["planned"] or ["— всё применено"]
                self.stdout.write(f"{slug}: " + ", ".join(pending))
            else:
                summary = ", ".join(f"{a}={m or '—'}"
                                    for a, m in sorted(result["applied"].items()))
                self.stdout.write(
                    self.style.SUCCESS(f"{slug}: {summary or '— нечего мигрировать'}")
                )

        if dry_run:
            return

        try:
            rebuilt = holding_views.rebuild_holding_views()
        except ProgrammingError as exc:
            # Схемы мигрированы, а собрать сводку поверх них нельзя: ветка
            # UNION ALL ссылается на столбец, которого у отставшей компании
            # ещё нет. Представления остаются СНЕСЁННЫМИ намеренно —
            # снесённая вьюха даёт читателю громкую ошибку, то есть верно
            # отражает состояние группы, а собранная по старому составу
            # молча врёт. Код возврата ненулевой: работа не доведена.
            partial = bool(opts["company"] or opts["app"] or opts["to"])
            why = ("Прогон был частичным, поэтому компании стоят на разных "
                   "версиях. " if partial else
                   "Схемы разошлись между компаниями. ")
            raise CommandError(
                "Схемы мигрированы, но сводки холдинга собрать нельзя. "
                + why
                + "Представления оставлены снесёнными: читатель получит "
                  "громкую ошибку вместо цифр по полумигрированной группе. "
                  "Доведите остальные компании — `manage.py migrate_companies` "
                  f"без фильтров. Причина: {exc}"
            ) from exc

        self.stdout.write(
            self.style.SUCCESS(f"Сводки холдинга собраны: {len(rebuilt)} шт.")
        )
