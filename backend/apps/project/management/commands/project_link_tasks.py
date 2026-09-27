"""Связать проекты доски задач с «Проектами» БЗО (A1.3).

Для каждого ``tasks.Project`` без ``project_ref`` заводит «Проект» (код —
``TP-<id доски>``: своего кода у доски нет; имя — имя доски; страна — KZ;
руководителя и заказчика заполняет человек потом) и пишет ссылку.
Идемпотентна: уже связанные доски пропускаются, а повтор после сбоя между
созданием «Проекта» и записью ссылки находит «Проект» по коду. Читает и пишет
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
        with use_company(company):
            linked = 0
            for board in tasks.projects_without_ref():
                project, _ = Project.objects.get_or_create(
                    code=f"TP-{board['id']}",
                    defaults={"name": board["name"], "country_code": "KZ"})
                tasks.set_project_ref(board["id"], str(project.id))
                linked += 1
        self.stdout.write(self.style.SUCCESS(f"Связано проектов: {linked}"))
