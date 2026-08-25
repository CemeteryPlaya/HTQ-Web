"""Аккаунт — владелец: его значения перезаписывают копию без вопросов.

План: docs/superpowers/plans/2026-08-25-hr-identity-sync.md, задача 5.
"""
from __future__ import annotations

import pytest

from apps.hr import interface as hr_interface
from apps.hr.models import Employee
from apps.hr.services import identity_sync_service as svc


@pytest.mark.django_db
def test_account_values_overwrite_copy(employee, account):
    Employee.objects.filter(pk=employee.id).update(phone="+7 700 000-00-00")

    changed = svc.sync_employee(employee.id)

    assert changed == ["phone"]
    assert Employee.objects.get(pk=employee.id).phone == account.phone


@pytest.mark.django_db
def test_second_pass_writes_nothing(employee):
    svc.sync_employee(employee.id)
    assert svc.sync_employee(employee.id) == []


@pytest.mark.django_db
def test_phone_format_difference_is_not_a_change(employee, account):
    # тот же номер, другая запись — синк не должен считать это расхождением
    Employee.objects.filter(pk=employee.id).update(phone="77051112233")
    account.phone = "+7 (705) 111-22-33"
    account.save()

    assert svc.sync_employee(employee.id) == []


@pytest.mark.django_db
def test_email_is_never_synced(employee, account):
    Employee.objects.filter(pk=employee.id).update(email="old@htq.test")
    account.email = "new@htq.test"
    account.save()

    svc.sync_employee(employee.id)

    assert Employee.objects.get(pk=employee.id).email == "old@htq.test"


@pytest.mark.django_db
def test_missing_account_is_expected_fallback(employee, fallback_log_mode):
    Employee.objects.filter(pk=employee.id).update(user_id=999999)

    assert svc.sync_employee(employee.id) == []


@pytest.mark.django_db
def test_employee_without_user_id_is_skipped(employee):
    Employee.objects.filter(pk=employee.id).update(user_id=None)

    assert svc.sync_employee(employee.id) == []


@pytest.mark.django_db
def test_interface_hook_updates_the_copy(employee, account):
    account.phone = "+7 777 999-88-77"
    account.save()

    hr_interface.notice_user_profile_changed(account.id)

    assert Employee.objects.get(pk=employee.id).phone == "+7 777 999-88-77"


@pytest.mark.django_db
def test_interface_hook_without_employee_is_noop(db, account):
    # аккаунт админа/внешнего пользователя — сотрудника нет, обновлять нечего
    hr_interface.notice_user_profile_changed(account.id)
