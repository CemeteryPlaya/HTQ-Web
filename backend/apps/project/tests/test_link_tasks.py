"""Команда связывания: проект задач получает ссылку на «Проект» БЗО."""

import pytest
from django.core.management import call_command

from apps.project.models import Project
from apps.tasks.models import Project as TaskProject


@pytest.mark.django_db
def test_every_task_project_gets_a_project(company_context):
    board = TaskProject.objects.create(name="Объект 15")
    call_command("project_link_tasks", "--company", company_context["slug"])
    board.refresh_from_db()
    project = Project.objects.get(pk=board.project_ref)
    # У доски нет своего кода — код «Проекта» выводится из её id.
    assert (project.name, project.code) == ("Объект 15", f"TP-{board.id}")
    call_command("project_link_tasks", "--company", company_context["slug"])  # идемпотентно
    assert Project.objects.count() == 1
