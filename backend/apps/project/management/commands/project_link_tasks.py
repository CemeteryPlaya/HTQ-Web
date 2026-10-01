"""Связать доски задач с «Проектами» БЗО (A1.3; D-02: «Проект» главный).

Существующие доски связала миграция ``tasks/0024``, а новые заводятся только
к «Проекту», поэтому команда — ремонтная: для доски, заведённой мимо
сервиса (ORM, старый сид), заводит «Проект» из её полей (название, статус,
сроки, руководитель — владелец доски; страна — KZ, заказчика заполняет
человек потом) и пишет ссылку. Код — ``TP-<id доски>``: своего кода у доски
нет. Код занят «Проектом», заведённым человеком (``created_by`` не пуст) или
уже отданным другой доске, — берётся ``TP-<id>-2``, ``-3``… и печатается;
«Проект», заведённый самой командой и ещё ничей (повтор после сбоя между
созданием «Проекта» и записью ссылки), переиспользуется. Идемпотентна.
Читает и пишет ``tasks`` через ``apps.tasks.interface`` — межаппный импорт
моделей запрещён; те же правила — в миграции ``tasks/0024``.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.project.models import Project
from apps.project.services import projects
from apps.tasks import interface as tasks
from htqweb.tenancy.db import use_company


class Command(BaseCommand):
    help = "Связать доски задач с «Проектами» модуля БЗО."

    def add_arguments(self, parser):
        parser.add_argument("--company", required=True)

    def handle(self, *args, company, **options):
        with use_company(company):
            linked = 0
            taken = tasks.linked_project_refs()
            for board in tasks.projects_without_ref():
                with transaction.atomic():
                    project = self._project_for(board, taken)
                    tasks.set_project_ref(board["id"], str(project.id))
                taken.add(str(project.id))
                linked += 1
        self.stdout.write(self.style.SUCCESS(f"Связано досок: {linked}"))

    def _project_for(self, board: dict, taken: set[str]) -> Project:
        fields = {key: board[key] for key in
                  ("name", "status", "date_start", "date_end", "manager_user_id")}
        base = f"TP-{board['id']}"
        code, n = base, 1
        while True:
            existing = Project.objects.filter(code=code).first()
            if existing is None:
                break
            if existing.created_by is None and str(existing.id) not in taken:
                return projects.update(existing, actor_id=None, **fields)
            n += 1
            code = f"{base}-{n}"
        if code != base:
            self.stdout.write(self.style.WARNING(
                f"Код {base} занят — доска {board['id']} связана с «Проектом» {code}."))
        return projects.create(code=code, country_code="KZ", actor_id=None, **fields)
