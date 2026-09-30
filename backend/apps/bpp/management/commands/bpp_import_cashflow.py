"""Импорт книги CashFlow в модуль БЗО (B6.2).

План и решения — ``docs/plans/2026-09-30-bpp-b62-import-cashflow.md``.

    manage.py bpp_import_cashflow <книга.xlsx> --company <slug> --draft-maps <папка>
    manage.py bpp_import_cashflow <книга.xlsx> --company <slug> --projects-map <csv> \\
        --articles-map <csv> --actor <user_id> [--dry-run] [--report <xlsx>]

Только добавляет (D-B62-1): договоры узнаются по LARK, операции — по
отпечатку строки, в том числе загруженные переносом «Договоров» (D-B62-4);
узнанное не переписывается, расхождения с книгой — лист отчёта «Расхождения
с книгой». Проекту без бюджета заводится черновик с листа «Бюджет» — ФД
утверждает его, и только тогда повторный запуск грузит договоры и операции
проекта (D-B62-2). Одна транзакция; ``--dry-run`` — с откатом, только отчёт.
"""

from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.bpp.services.actor import Actor
from apps.bpp.services.cashflow import maps, workbook
from apps.bpp.services.cashflow.load import CashflowLoader
from apps.bpp.services.migration.reference import MigrationStop
from apps.bpp.services.migration.report import MigrationReport
from htqweb.tenancy.db import use_company


class _DryRun(Exception):
    """Откат удачного прогона ``--dry-run``."""


class Command(BaseCommand):
    help = "Импорт книги CashFlow в модуль БЗО (B6.2): только добавляет новое."

    def add_arguments(self, parser):
        parser.add_argument("path", help="книга CashFlow.xlsx")
        parser.add_argument("--company", required=True, help="slug компании")
        parser.add_argument("--draft-maps", help="папка для черновиков карт; импорт не идёт")
        parser.add_argument("--projects-map", help="CSV «администратор → Проект»")
        parser.add_argument("--articles-map", help="CSV «администратор × код → статья»")
        parser.add_argument("--actor", type=int, help="user_id выполняющего импорт")
        parser.add_argument("--dry-run", action="store_true",
                            help="весь импорт с откатом — только отчёт")
        parser.add_argument("--report", help="xlsx-отчёт импорта")

    def handle(self, *args, **options):
        try:
            budget, registry, operations, warnings = workbook.load(options["path"])
        except workbook.WorkbookError as exc:
            raise CommandError(str(exc)) from exc
        for warning in warnings:
            self.stdout.write(self.style.WARNING(f"книга: {warning}"))
        names = maps.administrators(budget, registry, operations)
        used = maps.programs(budget, registry, operations)
        slug = options["company"]
        with use_company(slug):
            if options["draft_maps"]:
                folder = Path(options["draft_maps"])
                folder.mkdir(parents=True, exist_ok=True)
                maps.write_csv(folder / "projects.csv", maps.PROJECT_COLUMNS,
                               maps.draft_projects(names))
                maps.write_csv(folder / "articles.csv", maps.ARTICLE_COLUMNS,
                               maps.draft_articles(used, maps.article_index()))
                self.stdout.write(f"Черновики карт — в {folder}: projects.csv, articles.csv.")
                return
            if not (options["projects_map"] and options["articles_map"]):
                raise CommandError("Нужны обе карты: --projects-map и --articles-map. Черновики "
                                   "строит --draft-maps <папка>.")
            try:
                project_rows = maps.read_csv(Path(options["projects_map"]), maps.PROJECT_COLUMNS)
                article_rows = maps.read_csv(Path(options["articles_map"]), maps.ARTICLE_COLUMNS)
            except (OSError, ValueError) as exc:
                raise CommandError(str(exc)) from exc
            project_map, project_errors = maps.check_projects(project_rows, names)
            article_map, article_errors = maps.check_articles(article_rows, used,
                                                              maps.article_index())
            if project_errors or article_errors:
                raise CommandError("Импорт остановлен — карты неполные:\n  "
                                   + "\n  ".join(project_errors + article_errors))
            if not options["actor"]:
                raise CommandError("Нужен --actor <user_id> — кто выполняет импорт.")
            report = MigrationReport()
            loader = CashflowLoader(
                budget=budget, registry=registry, operations=operations,
                project_map=project_map, article_map=article_map,
                actor=Actor.for_user(options["actor"], company=slug, is_superuser=True),
                report=report)
            try:
                with transaction.atomic():
                    loader.run()
                    if options["dry_run"]:
                        raise _DryRun
            except _DryRun:
                pass
            except MigrationStop as exc:
                raise CommandError(f"Импорт остановлен, ничего не записано: {exc}") from exc
        if options["report"]:
            report.write_xlsx(Path(options["report"]))
        rows = report.rows
        waiting = sum(1 for row in rows["Не перенесено"]
                      if "не утверждён" in str(row.get("reason")))
        self.stdout.write(self.style.SUCCESS(
            ("Проверка без записи (--dry-run). " if options["dry_run"] else "Импорт выполнен. ")
            + f"Бюджеты-черновики: {len(rows['Бюджеты'])}, документы: {len(rows['Документы'])}, "
              f"ждут утверждения бюджета: {waiting}, "
              f"расхождения с книгой: {len(rows['Расхождения с книгой'])}, "
              f"не перенесено: {len(rows['Не перенесено']) - waiting}."))
