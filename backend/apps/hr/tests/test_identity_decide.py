"""Лестница подтверждающего и применение решения (спека §6.2, §9).

План: docs/superpowers/plans/2026-08-25-hr-identity-sync.md, задача 7.
"""
from __future__ import annotations

import pytest

from apps.hr.models import Employee, IdentityApprover, IdentityChangeRequest
from apps.hr.services import identity_request_service as svc


def _pending(employee, proposals: dict) -> IdentityChangeRequest:
    _, request = svc.capture(employee, dict(proposals), actor_id=1)
    assert request is not None
    return request


# ── кто подтверждает ────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_designated_approver_wins_over_department_manager(employee, manager_employee):
    employee.department.manager = manager_employee
    employee.department.save()
    IdentityApprover.objects.create(pk=1, user_id=777)

    assert svc.resolve_approver(employee) == 777


@pytest.mark.django_db
def test_falls_back_to_department_manager_when_unset(employee, manager_employee):
    employee.department.manager = manager_employee
    employee.department.save()

    assert svc.resolve_approver(employee) == manager_employee.user_id


@pytest.mark.django_db
def test_cleared_designation_returns_to_manager(employee, manager_employee):
    employee.department.manager = manager_employee
    employee.department.save()
    svc.set_approver(777, actor_id=1)
    svc.set_approver(None, actor_id=1)

    assert svc.resolve_approver(employee) == manager_employee.user_id


@pytest.mark.django_db
def test_no_approver_at_all_is_none(employee):
    assert svc.resolve_approver(employee) is None


# ── решение ─────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_apply_writes_account_and_syncs_copy(employee, account, fallback_log_mode):
    IdentityApprover.objects.create(pk=1, user_id=account.id)
    request = _pending(employee, {"first_name": "Иннокентий"})

    svc.decide(request.id, {"first_name": "apply"}, actor_id=account.id)

    account.refresh_from_db()
    assert account.first_name == "Иннокентий"
    # копия догнала владельца тем же вызовом, а не ждёт ночного прохода
    assert Employee.objects.get(pk=employee.id).first_name == "Иннокентий"
    request.refresh_from_db()
    assert request.status == IdentityChangeRequest.Status.APPLIED
    assert request.decided_by == account.id


@pytest.mark.django_db
def test_reject_touches_neither_side(employee, account, fallback_log_mode):
    IdentityApprover.objects.create(pk=1, user_id=account.id)
    before = account.first_name
    request = _pending(employee, {"first_name": "Иннокентий"})

    svc.decide(request.id, {"first_name": "reject"}, actor_id=account.id)

    account.refresh_from_db()
    assert account.first_name == before
    assert Employee.objects.get(pk=employee.id).first_name == before
    request.refresh_from_db()
    assert request.status == IdentityChangeRequest.Status.REJECTED


@pytest.mark.django_db
def test_partial_decision_applies_only_approved_field(employee, account, fallback_log_mode):
    IdentityApprover.objects.create(pk=1, user_id=account.id)
    request = _pending(employee, {"first_name": "Иннокентий", "phone": "+7 777 000-00-00"})

    svc.decide(request.id, {"first_name": "apply", "phone": "reject"}, actor_id=account.id)

    account.refresh_from_db()
    assert account.first_name == "Иннокентий"
    assert account.phone == "+7 705 111-22-33"


@pytest.mark.django_db
def test_incomplete_decision_is_refused(employee, account, fallback_log_mode):
    IdentityApprover.objects.create(pk=1, user_id=account.id)
    request = _pending(employee, {"first_name": "И", "phone": "+7 777 000-00-00"})

    with pytest.raises(svc.IncompleteDecision):
        svc.decide(request.id, {"first_name": "apply"}, actor_id=account.id)


@pytest.mark.django_db
def test_second_decision_is_refused(employee, account, fallback_log_mode):
    IdentityApprover.objects.create(pk=1, user_id=account.id)
    request = _pending(employee, {"first_name": "Иннокентий"})
    svc.decide(request.id, {"first_name": "apply"}, actor_id=account.id)

    with pytest.raises(svc.RequestClosed):
        svc.decide(request.id, {"first_name": "apply"}, actor_id=account.id)


@pytest.mark.django_db
def test_stranger_cannot_decide(employee, account, fallback_log_mode):
    IdentityApprover.objects.create(pk=1, user_id=account.id)
    request = _pending(employee, {"first_name": "Иннокентий"})

    with pytest.raises(svc.NotApprover):
        svc.decide(request.id, {"first_name": "apply"}, actor_id=999999)


@pytest.mark.django_db
def test_platform_admin_may_always_decide(employee, account, fallback_log_mode):
    IdentityApprover.objects.create(pk=1, user_id=account.id)
    request = _pending(employee, {"first_name": "Иннокентий"})

    svc.decide(request.id, {"first_name": "apply"}, actor_id=999999, is_admin=True)

    request.refresh_from_db()
    assert request.status == IdentityChangeRequest.Status.APPLIED


@pytest.mark.django_db
def test_unknown_request_raises(db):
    with pytest.raises(svc.RequestNotFound):
        svc.decide(999999, {}, actor_id=1, is_admin=True)


@pytest.mark.django_db
def test_stale_snapshot_is_visible_in_serialization(employee, account, fallback_log_mode):
    """Владелец уехал, пока заявка ждала — единственный настоящий конфликт."""
    request = _pending(employee, {"first_name": "Иннокентий"})
    account.first_name = "Совсем другое"
    account.save()

    row = next(f for f in svc.serialize(request)["fields"] if f["field"] == "first_name")

    assert row["is_stale"] is True
    assert row["account_value_now"] == "Совсем другое"
    assert row["account_value_at_request"] == "Иван"


@pytest.mark.django_db
def test_fresh_snapshot_is_not_flagged(employee, fallback_log_mode):
    request = _pending(employee, {"first_name": "Иннокентий"})

    row = next(f for f in svc.serialize(request)["fields"] if f["field"] == "first_name")

    assert row["is_stale"] is False
