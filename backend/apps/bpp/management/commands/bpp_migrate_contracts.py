"""Перенос данных из «Договоров» (``contracts``) в модуль БЗО (B6.1).

План и решения — ``docs/plans/2026-09-30-bpp-b61-migrate-contracts.md``.

    manage.py bpp_migrate_contracts --company <slug> --draft-maps <папка>
    manage.py bpp_migrate_contracts --company <slug> --projects-map <csv> \\
        --articles-map <csv> --actor <user_id> [--dry-run] [--report <xlsx>]

Первый вызов пишет черновики карт «администратор → Проект» и «программа →
статья» и отчёт конфликтов кодов, ничего не меняя в базе. ФД заполняет
карты; второй вызов проверяет их до первой записи — любой пропуск
останавливает перенос с перечнем. Данные ``contracts`` читаются только через
``apps.contracts.interface`` (сторож изоляции).

``--actor`` — кто выполняет перенос (обычно АДМ): его ``user_id`` пишется в
журнал изменений и становится автором документов, у которых в «Договорах»
автор пуст. Перенос идёт одной транзакцией: отказ на любом шаге откатывает
всё, ``--dry-run`` откатывает и удачный прогон — остаётся отчёт.
"""

from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.bpp.services.actor import Actor
from apps.bpp.services.migration import maps
from apps.bpp.services.migration.reference import MigrationStop
from apps.bpp.services.migration.run import MigrationContext, run
from apps.contracts import interface as contracts
from htqweb.tenancy.db import use_company


class _DryRun(Exception):
    """Откат удачного прогона ``--dry-run``."""


class Command(BaseCommand):
    help = "Перенос данных из «Договоров» (contracts) в модуль БЗО (B6.1)."

    def add_arguments(self, parser):
        parser.add_argument("--company", required=True, help="slug компании")
        parser.add_argument("--draft-maps", help="папка для черновиков карт; перенос не идёт")
        parser.add_argument("--projects-map", help="CSV «администратор → Проект»")
        parser.add_argument("--articles-map", help="CSV «программа → статья»")
        parser.add_argument("--actor", type=int,
                            help="user_id выполняющего перенос: журнал и автор документов "
                                 "без автора")
        parser.add_argument("--dry-run", action="store_true",
                            help="весь перенос с откатом — только отчёт")
        parser.add_argument("--report", help="xlsx-отчёт переноса")

    def handle(self, *args, **options):
        slug = options["company"]
        with use_company(slug):
            snapshot = contracts.migration_snapshot()
            if options["draft_maps"]:
                self._drafts(Path(options["draft_maps"]), snapshot)
                return
            if not (options["projects_map"] and options["articles_map"]):
                raise CommandError("Нужны обе карты: --projects-map и --articles-map. Черновики "
                                   "строит --draft-maps <папка>.")
            project_map, article_map = self._check_maps(snapshot, options)
            if not options["actor"]:
                raise CommandError("Нужен --actor <user_id> — кто выполняет перенос.")
            ctx = MigrationContext(snapshot=snapshot, project_map=project_map,
                                   article_map=article_map,
                                   actor=Actor.for_user(options["actor"], company=slug,
                                                        is_superuser=True))
            try:
                with transaction.atomic():
                    run(ctx)
                    if options["dry_run"]:
                        raise _DryRun
            except _DryRun:
                pass
            except MigrationStop as exc:
                raise CommandError(f"Перенос остановлен, ничего не записано: {exc}") from exc
        if options["report"]:
            ctx.report.write_xlsx(Path(options["report"]))
        rows = ctx.report.rows
        self.stdout.write(self.style.SUCCESS(
            ("Проверка без записи (--dry-run). " if options["dry_run"] else "Перенос выполнен. ")
            + f"Проекты: {len(rows['Проекты'])}, контрагенты: {len(rows['Контрагенты'])}, "
              f"бюджеты: {len(rows['Бюджеты'])}, документы: {len(rows['Документы'])}, "
              f"переотправить: {len(rows['Переотправить'])}, "
              f"не перенесено: {len(rows['Не перенесено'])}."))

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
