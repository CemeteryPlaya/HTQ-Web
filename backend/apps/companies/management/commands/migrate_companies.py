"""Команда прогона миграций по схемам компаний.

Тонкая обёртка над apps.companies.services.migration_service: вся логика —
там, здесь только разбор аргументов и печать. Отдельная команда, а не флаг
штатной ``migrate``, потому что ``migrate`` работает с public и знать про
схемы компаний не должна.
"""

from django.core.management.base import BaseCommand, CommandError

from apps.companies.interface import active_company_slugs
from apps.companies.models import Company
from apps.companies.services import migration_service


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

        for slug in slugs:
            try:
                result = migration_service.migrate_company(
                    slug, app_label=opts["app"], target=opts["to"],
                    plan=opts["plan"],
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

            if opts["plan"]:
                pending = result["planned"] or ["— всё применено"]
                self.stdout.write(f"{slug}: " + ", ".join(pending))
            else:
                summary = ", ".join(f"{a}={m or '—'}"
                                    for a, m in sorted(result["applied"].items()))
                self.stdout.write(
                    self.style.SUCCESS(f"{slug}: {summary or '— нечего мигрировать'}")
                )
