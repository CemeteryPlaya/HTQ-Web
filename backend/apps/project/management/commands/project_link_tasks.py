"""Связать проекты доски задач с «Проектами» БЗО (A1.3).

Для каждого ``tasks.Project`` без ``project_ref`` заводит «Проект» (код —
``TP-<id доски>``: своего кода у доски нет; имя — имя доски; страна — KZ;
руководителя и заказчика заполняет человек потом) и пишет ссылку.
Идемпотентна: уже связанные доски пропускаются, а повтор после сбоя между
созданием «Проекта» и записью ссылки находит «Проект» по коду. Переиспользуется
только «Проект», заведённый самой командой (``created_by`` пуст): «Проект»,
который человек сам создал с кодом ``TP-<n>``, чужой — доска ``n`` тогда не
связывается, а код печатается как конфликт. Читает и пишет
``tasks`` через ``apps.tasks.interface`` — межаппный импорт моделей запрещён.
"""

from django.core.management.base import BaseCommand

from apps.project.models import Project
from apps.tasks import interface as tasks
from htqweb.tenancy.db import use_company


class Command(BaseCommand):
    help = "Связать проекты доски задач с «Проектами» модуля БЗО."

    def add_arguments(self, parser):
        parser.add_argument("--company", required=True)

    def handle(self, *args, company, **options):
        conflicts: list[str] = []
        with use_company(company):
            linked = 0
            for board in tasks.projects_without_ref():
                code = f"TP-{board['id']}"
                project, _ = Project.objects.get_or_create(
                    code=code, defaults={"name": board["name"], "country_code": "KZ"})
                if project.created_by is not None:
                    conflicts.append(code)
                    continue
                tasks.set_project_ref(board["id"], str(project.id))
                linked += 1
        self.stdout.write(self.style.SUCCESS(f"Связано проектов: {linked}"))
        for code in conflicts:
            self.stdout.write(self.style.WARNING(
                f"Код {code} занят «Проектом», заведённым вручную, — доска не связана. "
                f"Свяжите её руками или переименуйте тот «Проект»."))
