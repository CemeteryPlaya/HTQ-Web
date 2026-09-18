"""Кадровая правка идентичности не применяется, а становится заявкой.

Это главный инвариант всей функции: копия в Employee не источник правды, и
правка, попавшая в неё напрямую, означала бы молчаливое расхождение с
владельцем (спека §3).

План: docs/superpowers/plans/2026-08-25-hr-identity-sync.md, задача 6.
"""
from __future__ import annotations

import pytest

from apps.hr import schemas
from apps.hr.models import Employee, IdentityChangeRequest
from apps.hr.services import employee_service as emp_svc


@pytest.mark.django_db
def test_identity_edit_becomes_request_not_a_write(employee, account):
    emp_svc.update_employee(
        employee.id,
        schemas.EmployeeUpdate(first_name="Иннокентий", phone="+7 777 000-00-00"),
        changed_by_id=42,
    )

    assert Employee.objects.get(pk=employee.id).first_name == account.first_name
    request = IdentityChangeRequest.objects.get(employee=employee)
    assert request.status == IdentityChangeRequest.Status.PENDING
    assert request.created_by == 42
    assert request.source == IdentityChangeRequest.Source.HR_FORM
    assert {row.field for row in request.fields.all()} == {"first_name", "phone"}


@pytest.mark.django_db
def test_labour_fields_apply_immediately(employee, other_position):
    emp_svc.update_employee(
        employee.id,
        schemas.EmployeeUpdate(position_id=other_position.id, first_name="Иннокентий"),
        changed_by_id=42,
    )

    assert Employee.objects.get(pk=employee.id).position_id == other_position.id


@pytest.mark.django_db
def test_skeleton_without_account_is_written_directly(employee):
    Employee.objects.filter(pk=employee.id).update(user_id=None)

    emp_svc.update_employee(
        employee.id, schemas.EmployeeUpdate(first_name="Иннокентий"), changed_by_id=42,
    )

    assert Employee.objects.get(pk=employee.id).first_name == "Иннокентий"
    assert not IdentityChangeRequest.objects.filter(employee=employee).exists()


@pytest.mark.django_db
def test_value_equal_to_account_creates_no_request(employee, account):
    emp_svc.update_employee(
        employee.id, schemas.EmployeeUpdate(first_name=account.first_name),
        changed_by_id=42,
    )

    assert not IdentityChangeRequest.objects.filter(employee=employee).exists()


@pytest.mark.django_db
def test_phone_reformatting_creates_no_request(employee):
    # тот же номер, другая запись — заявка на пустом месте недопустима
    emp_svc.update_employee(
        employee.id, schemas.EmployeeUpdate(phone="77051112233"), changed_by_id=42,
    )

    assert not IdentityChangeRequest.objects.filter(employee=employee).exists()


@pytest.mark.django_db
def test_second_edit_extends_open_request(employee):
    emp_svc.update_employee(
        employee.id, schemas.EmployeeUpdate(first_name="Иннокентий"), changed_by_id=42,
    )
    emp_svc.update_employee(
        employee.id, schemas.EmployeeUpdate(phone="+7 777 000-00-00"), changed_by_id=42,
    )

    request = IdentityChangeRequest.objects.get(employee=employee)
    assert {row.field for row in request.fields.all()} == {"first_name", "phone"}


@pytest.mark.django_db
def test_repeated_edit_of_same_field_overwrites_proposal(employee):
    emp_svc.update_employee(
        employee.id, schemas.EmployeeUpdate(first_name="Первый"), changed_by_id=42,
    )
    emp_svc.update_employee(
        employee.id, schemas.EmployeeUpdate(first_name="Второй"), changed_by_id=42,
    )

    request = IdentityChangeRequest.objects.get(employee=employee)
    assert request.fields.get(field="first_name").proposed_value == "Второй"


@pytest.mark.django_db
def test_email_is_not_captured_as_proposal(employee):
    """email — сигнал, а не предмет заявки: менять логин заявкой нельзя."""
    emp_svc.update_employee(
        employee.id, schemas.EmployeeUpdate(email="new@htq.test"), changed_by_id=42,
    )

    assert Employee.objects.get(pk=employee.id).email == "new@htq.test"
    assert not IdentityChangeRequest.objects.filter(employee=employee).exists()
