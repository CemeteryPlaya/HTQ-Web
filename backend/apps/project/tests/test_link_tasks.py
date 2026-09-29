"""Команда связывания: доска задач получает ссылку на «Проект» БЗО."""

from datetime import date
from io import StringIO

import pytest
from django.core.management import call_command

from apps.project.models import Project
from apps.tasks.models import Project as TaskProject


@pytest.mark.django_db
def test_every_task_project_gets_a_project(company_context):
    board = TaskProject.objects.create(name="Объект 15", status="completed", owner_id=7,
                                       start_date=date(2026, 1, 1), end_date=date(2026, 6, 30))
    call_command("project_link_tasks", "--company", company_context["slug"])
    board.refresh_from_db()
    project = Project.objects.get(pk=board.project_ref)
    # У доски нет своего кода — код «Проекта» выводится из её id; поля
    # доски переезжают в «Проект», и доска дальше повторяет его.
    assert (project.name, project.code) == ("Объект 15", f"TP-{board.id}")
    assert (project.status, project.date_start, project.date_end, project.manager_user_id) == (
        "closed", date(2026, 1, 1), date(2026, 6, 30), 7)
    assert project.members.filter(user_id=7).exists()
    call_command("project_link_tasks", "--company", company_context["slug"])  # идемпотентно
    assert Project.objects.count() == 1


@pytest.mark.django_db
def test_manual_project_with_the_same_code_is_not_hijacked(company_context):
    """«Проект», который человек сам завёл с кодом ``TP-<n>``, не становится
    проектом доски ``n``: переиспользуется только заведённый самой командой
    (повтор после сбоя), а доска получает код с суффиксом — и он печатается."""
    board = TaskProject.objects.create(name="Объект 15")
    manual = Project.objects.create(code=f"TP-{board.id}", name="Чужой", country_code="KZ",
                                    created_by=5)
    out = StringIO()
    call_command("project_link_tasks", "--company", company_context["slug"], stdout=out)
    board.refresh_from_db()
    project = Project.objects.get(pk=board.project_ref)
    assert project.pk != manual.pk and project.code == f"TP-{board.id}-2"
    assert Project.objects.get(pk=manual.pk).name == "Чужой"
    assert f"TP-{board.id}-2" in out.getvalue()


@pytest.mark.django_db
def test_leftover_of_a_crashed_run_is_reused(company_context):
    """Сбой между созданием «Проекта» и записью ссылки: повтор находит
    «Проект» команды по коду и берёт его, а не заводит второй."""
    board = TaskProject.objects.create(name="Объект 15")
    leftover = Project.objects.create(code=f"TP-{board.id}", name="Старое имя",
                                      country_code="KZ")
    call_command("project_link_tasks", "--company", company_context["slug"])
    board.refresh_from_db()
    assert board.project_ref == str(leftover.pk)
    assert Project.objects.get(pk=leftover.pk).name == "Объект 15"
