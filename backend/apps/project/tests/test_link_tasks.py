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


@pytest.mark.django_db
def test_manual_project_with_the_same_code_is_not_hijacked(company_context):
    """«Проект», который человек сам завёл с кодом ``TP-<n>``, не становится
    проектом доски ``n``: переиспользуется только заведённый самой командой
    (повтор после сбоя), а занятый код — конфликт в выводе."""
    from io import StringIO

    board = TaskProject.objects.create(name="Объект 15")
    manual = Project.objects.create(code=f"TP-{board.id}", name="Чужой", country_code="KZ",
                                    created_by=5)
    out = StringIO()
    call_command("project_link_tasks", "--company", company_context["slug"], stdout=out)
    board.refresh_from_db()
    assert board.project_ref == ""
    assert Project.objects.count() == 1 and Project.objects.get().pk == manual.pk
    assert f"TP-{board.id}" in out.getvalue()
