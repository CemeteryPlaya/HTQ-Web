"""Загрузка реестра договоров заказчика из CashFlow.xlsx.

    python manage.py import_cashflow CashFlow.xlsx [--dry-run] [--year 2026]
                                     [--country Казахстан] [--status signed]

Вся работа — в ``apps/contracts/services/cashflow_import.py`` (правило:
логика живёт в ``services/``, команда только разбирает аргументы и печатает
отчёт). Там же — все правила чинки данных и причины, по которым они такие.

``--dry-run`` читает и раскладывает всё то же самое, но откатывает
транзакцию: отчёт получается полный, включая предупреждения и перерасходы,
а база остаётся нетронутой. Прогонять первым имеет смысл всегда — книгу
ведут руками, и «сколько строк не поедет» лучше узнать до записи.
"""

from django.core.management.base import BaseCommand, CommandError

from apps.contracts.models import AgreementStatus
from apps.contracts.services import cashflow_import


class Command(BaseCommand):
    help = "Загрузить реестр договоров и лимиты бюджета из книги CashFlow.xlsx"

    def add_arguments(self, parser):
        parser.add_argument("path", help="Путь к .xlsx с листами «Бюджет» и «Реестр договоров»")
        parser.add_argument("--dry-run", action="store_true",
                            help="Прочитать и показать отчёт, ничего не записывая")
        parser.add_argument("--year", type=int, default=None,
                            help="Год бюджетов (по умолчанию — год самой поздней даты подписания)")
        parser.add_argument("--country", default=cashflow_import.DEFAULT_COUNTRY,
                            help="Страна администраторов и контрагентов "
                                 f"(в книге её нет; по умолчанию «{cashflow_import.DEFAULT_COUNTRY}»)")
        parser.add_argument("--status", default=AgreementStatus.SIGNED,
                            choices=[value for value, _ in AgreementStatus.choices],
                            help="Статус загружаемых договоров (по умолчанию «подписан»: "
                                 "дата подписания есть у каждой строки реестра)")

    def handle(self, *args, **options):
        try:
            report = cashflow_import.run_import(
                options["path"],
                year=options["year"],
                country_name=options["country"],
                status=options["status"],
                dry_run=options["dry_run"],
            )
        except cashflow_import.CashflowImportError as exc:
            raise CommandError(str(exc)) from exc
        except FileNotFoundError as exc:
            raise CommandError(f"файл не найден: {options['path']}") from exc

        self._print(report)

    def _print(self, report: cashflow_import.ImportReport) -> None:
        write = self.stdout.write

        write("")
        write(f"Строк реестра прочитано: {report.rows_read}")
        write("")
        write(f"{'Сущность':<18}{'создано':>10}{'обновлено':>12}")
        write("-" * 40)
        for entity in sorted(set(report.created) | set(report.updated)):
            write(f"{entity:<18}{report.created.get(entity, 0):>10}"
                  f"{report.updated.get(entity, 0):>12}")

        if report.warnings:
            write("")
            write(self.style.WARNING(f"Требуют внимания ({len(report.warnings)}):"))
            for warning in report.warnings:
                write(f"  • {warning}")

        if report.overruns:
            write("")
            write(self.style.WARNING(f"Перерасход бюджета ({len(report.overruns)}):"))
            for overrun in report.overruns:
                write(f"  • {overrun}")

        write("")
        if report.dry_run:
            write(self.style.NOTICE("--dry-run: транзакция откачена, база не изменена"))
        else:
            write(self.style.SUCCESS("Загрузка завершена"))
