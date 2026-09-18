"""Ночная сверка не чинит молча (спека §8).

Найденное кадровое значение оформляется заявкой ДО перезаписи копии: иначе
между двумя шагами оно существовало бы только в памяти воркера и терялось бы
при падении. Дрейф помечается fallback'ом с expected=False — это не штатная
деградация, а сигнал, что какой-то путь пишет в копию мимо правила, поэтому
тесты просят прод-режим подмен через fixture fallback_log_mode.

План: docs/superpowers/plans/2026-08-25-hr-identity-sync.md, задача 10.
"""
from __future__ import annotations

import datetime

import pytest

from apps.hr.models import Employee, IdentityChangeRequest
from apps.hr.services import identity_sync_service as svc
from apps.hr.tasks import sync_identity


@pytest.fixture
def employee_in_company(account, company_context):
    """Сотрудник, реально живущий в схеме компании ``company_context``.

    hr — tenant-аппка: ``Department``/``Position``/``Employee`` этой
    фикстуры обязаны существовать в СХЕМЕ компании, а не в public, иначе
    ``sync_identity(company_slug=...)`` (теперь @company_task, читает
    именно схему компании) их не увидит. Явная зависимость от
    ``company_context`` в сигнатуре — не порядок аргументов теста —
    гарантирует, что запись идёт уже под установленным search_path: pytest
    настраивает зависимость (``company_context``) раньше зависящей от неё
    фикстуры.

    Не переиспользует общую фикстуру ``employee`` из conftest.py намеренно:
    та создаётся под голым ``db`` (без компании) и её используют файлы, не
    трогающие задачу — привязка её к компании увеличила бы стоимость (схема
    + миграции) всем им, не только этому файлу.
    """
    from apps.hr.models import Department, Position

    department = Department.objects.create(name="Строительство", path="build")
    position = Position.objects.create(title="Инженер", department=department, weight=10)
    return Employee.objects.create(
        email="ivanov@htq.test", department=department, position=position,
        hire_date=datetime.date(2024, 1, 9), user_id=account.id,
        first_name=account.first_name, last_name=account.last_name,
        middle_name=account.patronymic, phone=account.phone, bio=account.bio,
    )


@pytest.mark.django_db
def test_drift_becomes_request_then_copy_restored(employee, account, fallback_log_mode):
    # правка мимо API: прямой UPDATE, как это сделал бы django-admin или SQL
    Employee.objects.filter(pk=employee.id).update(first_name="Дрейф")

    svc.reconcile_employee(employee.id)

    request = IdentityChangeRequest.objects.get(employee=employee)
    assert request.source == IdentityChangeRequest.Source.NIGHTLY
    assert request.created_by is None
    assert request.fields.get(field="first_name").proposed_value == "Дрейф"
    # копия восстановлена из аккаунта — владелец есть владелец
    assert Employee.objects.get(pk=employee.id).first_name == account.first_name


@pytest.mark.django_db
def test_clean_employee_creates_nothing(employee, fallback_log_mode):
    assert svc.reconcile_employee(employee.id) is None
    assert not IdentityChangeRequest.objects.filter(employee=employee).exists()


@pytest.mark.django_db(transaction=True)
def test_task_reports_counts(employee_in_company, company_context, fallback_log_mode):
    Employee.objects.filter(pk=employee_in_company.id).update(phone="+7 999 999-99-99")

    assert sync_identity(company_slug=company_context["slug"]) == \
        {"checked": 1, "requests": 1}


@pytest.mark.django_db(transaction=True)
def test_task_skips_unlinked_employees(employee_in_company, company_context, fallback_log_mode):
    Employee.objects.filter(pk=employee_in_company.id).update(user_id=None)

    assert sync_identity(company_slug=company_context["slug"]) == \
        {"checked": 0, "requests": 0}


@pytest.mark.django_db(transaction=True)
def test_task_skips_terminated(employee_in_company, company_context, fallback_log_mode):
    Employee.objects.filter(pk=employee_in_company.id).update(
        status="terminated", first_name="Дрейф",
    )

    assert sync_identity(company_slug=company_context["slug"]) == \
        {"checked": 0, "requests": 0}


@pytest.mark.django_db
def test_task_requires_company_slug():
    """@company_task обязателен: без company_slug — MissingCompanyArgument,
    а не молчаливый public (см. htqweb/tenancy/celery.py)."""
    from htqweb.tenancy.celery import MissingCompanyArgument

    with pytest.raises(MissingCompanyArgument):
        sync_identity()


@pytest.mark.django_db
def test_reconcile_without_account_is_expected(employee, fallback_log_mode):
    Employee.objects.filter(pk=employee.id).update(user_id=999999)

    assert svc.reconcile_employee(employee.id) is None
