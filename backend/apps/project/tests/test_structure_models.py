"""Модели проектной структуры (спек 2026-10-06 §2): ограничения БД, удаление
проекта со структурой и сид справочника ролей только в схеме компании."""

import importlib
from datetime import date
from types import SimpleNamespace

import pytest
from django.apps import apps as django_apps
from django.db import IntegrityError, connection, transaction

from apps.project.models import (Project, ProjectAssignment, ProjectPart, ProjectRole,
                                 ProjectSlot)

seed_migration = importlib.import_module("apps.project.migrations.0005_seed_project_roles")


def _project(code="П-100"):
    return Project.objects.create(code=code, name="Объект", country_code="KZ")


def _role(name, level, part=ProjectPart.OFFICE):
    return ProjectRole.objects.create(name=name, level=level, default_part=part)


@pytest.mark.django_db
def test_role_level_is_one_to_four(company_context):
    for bad in (0, 5):
        with pytest.raises(IntegrityError), transaction.atomic():
            _role(f"Роль {bad}", bad)
    assert _role("Тест L4", 4).level == 4


@pytest.mark.django_db
def test_slot_plan_and_assignment_dates_are_checked(company_context):
    project, role = _project(), _role("Тест-ГД", 1)
    with pytest.raises(IntegrityError), transaction.atomic():
        ProjectSlot.objects.create(project=project, role=role, part="office", planned_headcount=0)
    slot = ProjectSlot.objects.create(project=project, role=role, part="office")
    with pytest.raises(IntegrityError), transaction.atomic():
        ProjectAssignment.objects.create(slot=slot, employee_id=1, date_from=date(2026, 5, 2),
                                         date_to=date(2026, 5, 1))
    ProjectAssignment.objects.create(slot=slot, employee_id=1, date_from=date(2026, 5, 2),
                                     date_to=date(2026, 5, 2))


@pytest.mark.django_db
def test_project_with_structure_can_be_deleted(company_context):
    """Подчинение мест — ``RESTRICT``: удаление проекта каскадом сносит и
    руководителя, и подчинённого, ``PROTECT`` уронил бы его."""
    project = _project()
    top = ProjectSlot.objects.create(project=project, role=_role("Тест-ГД", 1), part="office")
    child = ProjectSlot.objects.create(project=project, role=_role("Тест-спец", 3),
                                       part="site", parent=top)
    ProjectAssignment.objects.create(slot=child, employee_id=5, date_from=date(2026, 1, 1))
    Project.objects.filter(pk=project.pk).delete()
    assert not ProjectSlot.objects.exists() and not ProjectAssignment.objects.exists()


def _run_seed():
    seed_migration.seed(django_apps, SimpleNamespace(connection=connection))


@pytest.mark.django_db
def test_seed_fills_empty_catalog_in_company_schema(company_context):
    ProjectRole.objects.all().delete()
    _run_seed()
    assert list(ProjectRole.objects.values_list("name", "level", "default_part")) == [
        ("Руководитель проекта (ГД)", 1, "office"),
        ("Заместитель директора", 2, "office"),
        ("Технический директор", 2, "office"),
        ("Специалист", 3, "office"),
        ("Рабочий", 4, "site"),
    ]


@pytest.mark.django_db
def test_seed_leaves_filled_catalog_alone(company_context):
    ProjectRole.objects.all().delete()
    _role("Своя роль", 2)
    _run_seed()
    assert list(ProjectRole.objects.values_list("name", flat=True)) == ["Своя роль"]


@pytest.mark.django_db
def test_seed_writes_nothing_in_public(db):
    ProjectRole.objects.all().delete()
    _run_seed()
    assert not ProjectRole.objects.exists()
