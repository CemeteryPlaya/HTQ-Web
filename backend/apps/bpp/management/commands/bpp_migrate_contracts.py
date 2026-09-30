"""Перенос данных из «Договоров» (``contracts``) в модуль БЗО (B6.1).

План и решения — ``docs/plans/2026-09-30-bpp-b61-migrate-contracts.md``.

    manage.py bpp_migrate_contracts --company <slug> --draft-maps <папка>
    manage.py bpp_migrate_contracts --company <slug> --projects-map <csv> \\
        --articles-map <csv> [--default-author <user_id>] [--dry-run] [--report <xlsx>]

Первый вызов пишет черновики карт «администратор → Проект» и «программа →
статья» и отчёт конфликтов кодов, ничего не меняя в базе. ФД заполняет
карты; второй вызов проверяет их до первой записи — любой пропуск
останавливает перенос с перечнем. Данные ``contracts`` читаются только через
``apps.contracts.interface`` (сторож изоляции).
"""

from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.bpp.services.migration import maps
from apps.contracts import interface as contracts
from htqweb.tenancy.db import use_company


class Command(BaseCommand):
    help = "Перенос данных из «Договоров» (contracts) в модуль БЗО (B6.1)."

    def add_arguments(self, parser):
        parser.add_argument("--company", required=True, help="slug компании")
        parser.add_argument("--draft-maps", help="папка для черновиков карт; перенос не идёт")
        parser.add_argument("--projects-map", help="CSV «администратор → Проект»")
        parser.add_argument("--articles-map", help="CSV «программа → статья»")
        parser.add_argument("--default-author", type=int,
                            help="автор документов, у которых в «Договорах» он пуст")
        parser.add_argument("--dry-run", action="store_true",
                            help="весь перенос с откатом — только отчёт")
        parser.add_argument("--report", help="xlsx-отчёт переноса")

    def handle(self, *args, **options):
        with use_company(options["company"]):
            snapshot = contracts.migration_snapshot()
            if options["draft_maps"]:
                self._drafts(Path(options["draft_maps"]), snapshot)
                return
            if not (options["projects_map"] and options["articles_map"]):
                raise CommandError("Нужны обе карты: --projects-map и --articles-map. Черновики "
                                   "строит --draft-maps <папка>.")
            self._check_maps(snapshot, options)
        self.stdout.write(self.style.SUCCESS("Карты проверены."))

    def _drafts(self, folder: Path, snapshot: dict) -> None:
        folder.mkdir(parents=True, exist_ok=True)
        articles = maps.article_index()
        maps.write_csv(folder / "projects.csv", maps.PROJECT_COLUMNS,
                       maps.draft_projects(snapshot))
        rows, conflicts = maps.draft_articles(snapshot, articles)
        maps.write_csv(folder / "articles.csv", maps.ARTICLE_COLUMNS, rows)
        (folder / "conflicts.txt").write_text(
            "\n".join(conflicts) or "Конфликтов кодов программ нет.", encoding="utf-8")
        empty = sum(1 for row in rows if not row["article_code"])
        self.stdout.write(f"Черновики карт — в {folder}: projects.csv, articles.csv, "
                          f"conflicts.txt. Статья не предложена у {empty} программ из "
                          f"{len(rows)}; конфликтов кодов: {len(conflicts)}.")

    def _check_maps(self, snapshot: dict, options) -> tuple[dict, dict]:
        try:
            project_rows = maps.read_csv(Path(options["projects_map"]), maps.PROJECT_COLUMNS)
            article_rows = maps.read_csv(Path(options["articles_map"]), maps.ARTICLE_COLUMNS)
        except (OSError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        project_map, project_errors = maps.check_projects(project_rows, snapshot)
        article_map, article_errors = maps.check_articles(article_rows, snapshot,
                                                          maps.article_index())
        errors = project_errors + article_errors
        if errors:
            raise CommandError("Перенос остановлен — карты неполные:\n  " + "\n  ".join(errors))
        return project_map, article_map
