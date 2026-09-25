"""Загрузка листа «Операции» (счета по договорам и без) из книги CashFlow.

    python manage.py import_cashflow_operations "CashFlow pr.xlsx" [--dry-run]
                    [--year 2026] [--country Казахстан] [--status paid]

Запускается ПОСЛЕ ``import_cashflow``: оплаты по договорам ищут договоры по
идентификатору LARK, загруженному тем импортом. Сам реестр этот импорт не
перечитывает и договоры не трогает.

Логика — в ``apps/contracts/services/cashflow_operations_import.py``, там же
все правила разбора и причины, по которым они такие. ``--dry-run`` делает
всё то же и откатывает транзакцию; первым прогоном — всегда он.
"""

from django.core.management.base import BaseCommand, CommandError

from apps.contracts.services import cashflow_import
from apps.contracts.services import cashflow_operations_import as operations

from .import_cashflow import print_report


class Command(BaseCommand):
    help = "Загрузить счета из листа «Операции» книги CashFlow (после import_cashflow)"

    def add_arguments(self, parser):
        parser.add_argument("path", help="Путь к .xlsx с листами «Бюджет» и «Операции»")
        parser.add_argument("--dry-run", action="store_true",
                            help="Прочитать и показать отчёт, ничего не записывая")
        parser.add_argument("--year", type=int, default=None,
                            help="Год бюджетов для заводимых строк "
                                 "(по умолчанию — год самого позднего счёта)")
        parser.add_argument("--country", default=cashflow_import.DEFAULT_COUNTRY,
                            help="Страна новых администраторов и поставщиков "
                                 f"(по умолчанию «{cashflow_import.DEFAULT_COUNTRY}»)")
        parser.add_argument("--status", default="paid",
                            choices=list(operations.STATUS_PRESETS),
                            help="paid — счета оплачены, оплаты проведены (по умолчанию); "
                                 "approved — согласованы и ждут оплаты; draft — черновики "
                                 "(в остатке бюджета не учитываются)")

    def handle(self, *args, **options):
        try:
            report = operations.run_import(
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

        print_report(self, report, rows_label="Строк листа «Операции» прочитано")
