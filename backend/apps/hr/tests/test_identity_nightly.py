"""Ночная сверка не чинит молча (спека §8).

Найденное кадровое значение оформляется заявкой ДО перезаписи копии: иначе
между двумя шагами оно существовало бы только в памяти воркера и терялось бы
при падении. Дрейф помечается fallback'ом с expected=False — это не штатная
деградация, а сигнал, что какой-то путь пишет в копию мимо правила, поэтому
тесты просят прод-режим подмен через fixture fallback_log_mode.

План: docs/superpowers/plans/2026-08-25-hr-identity-sync.md, задача 10.
"""
from __future__ import annotations

import pytest

from apps.hr.models import Employee, IdentityChangeRequest
from apps.hr.services import identity_sync_service as svc
from apps.hr.tasks import sync_identity


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


@pytest.mark.django_db
def test_task_reports_counts(employee, fallback_log_mode):
    Employee.objects.filter(pk=employee.id).update(phone="+7 999 999-99-99")

    assert sync_identity() == {"checked": 1, "requests": 1}


@pytest.mark.django_db
def test_task_skips_unlinked_employees(employee, fallback_log_mode):
    Employee.objects.filter(pk=employee.id).update(user_id=None)

    assert sync_identity() == {"checked": 0, "requests": 0}


@pytest.mark.django_db
def test_task_skips_terminated(employee, fallback_log_mode):
    Employee.objects.filter(pk=employee.id).update(
        status="terminated", first_name="Дрейф",
    )

    assert sync_identity() == {"checked": 0, "requests": 0}


@pytest.mark.django_db
def test_reconcile_without_account_is_expected(employee, fallback_log_mode):
    Employee.objects.filter(pk=employee.id).update(user_id=999999)

    assert svc.reconcile_employee(employee.id) is None
