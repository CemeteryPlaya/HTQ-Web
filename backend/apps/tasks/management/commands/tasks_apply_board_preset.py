"""Применить шаблон процесса к доске задач (канбан, решение K-40, этап S4).

``manage.py tasks_apply_board_preset --company <slug> (--department ID | --project ID)
[--preset htq_process] [--actor USER_ID] [--dry-run]``

Шаблон «Процесс задач HTQ» (``services/automation/presets.py``): колонки,
поля «Причина ожидания» и «Взята в работу», метки «Протокольные поручения» и
«Просрочено», шаблон чек-листа «Чек-лист», правила, запреты ручного переноса,
команда «Просрочено» и кнопки «Взять в работу», «На доработку», «Сдать».
Идемпотентна: повтор правит автоматизации шаблона, а не дублирует их; прочие
поля, шаблоны и автоматизации доски не трогает. ``--dry-run`` печатает тот же
отчёт и откатывает всё. Права не проверяются — команда для администратора
платформы; в интерфейсе то же делает администратор доски кнопкой настроек.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.tasks.models import BoardKind
from apps.tasks.services import board_service
from apps.tasks.services.automation import presets
from htqweb.errors import DomainError
from htqweb.tenancy.db import use_company


class Command(BaseCommand):
    help = "Применить шаблон процесса (по умолчанию «Процесс задач HTQ») к доске задач."

    def add_arguments(self, parser):
        parser.add_argument("--company", required=True, help="Слаг компании.")
        target = parser.add_mutually_exclusive_group(required=True)
        target.add_argument("--department", type=int, help="Доска отдела: id отдела.")
        target.add_argument("--project", type=int, help="Доска проекта задач: id проекта задач.")
        parser.add_argument("--preset", default="htq_process", choices=presets.PRESETS)
        parser.add_argument("--actor", type=int, default=None,
                            help="Кого записать автором автоматизаций (id учётки).")
        parser.add_argument("--dry-run", action="store_true",
                            help="Показать, что изменится, и ничего не записать.")

    def handle(self, *args, **options):
        kind = BoardKind.DEPARTMENT if options["department"] else BoardKind.PROJECT
        board_id = options["department"] or options["project"]
        with use_company(options["company"]):
            board = board_service.board_for(kind, board_id)
            if kind == BoardKind.PROJECT and board.project is None:
                raise CommandError(f"Проекта задач {board_id} нет в компании {options['company']}")
            try:
                report = presets.apply(board, options["preset"], options["actor"],
                                       dry_run=options["dry_run"])
            except DomainError as exc:
                raise CommandError(exc.message) from exc
        title = "Пробный прогон — ничего не записано" if options["dry_run"] else "Применено"
        self.stdout.write(f"{title}: шаблон {report['preset']} → доска {kind} {board_id}")
        outcomes = {"created": "заведены", "kept": "уже есть", "updated": "обновлены"}
        for section, label in (("fields", "Поля"), ("labels", "Метки"),
                               ("templates", "Шаблоны чек-листов"),
                               ("automations", "Автоматизации")):
            for outcome, names in report[section].items():
                if names:
                    self.stdout.write(f"  {label} — {outcomes[outcome]}: {', '.join(names)}")
