"""Инварианты хранения заявок.

Частичный уникальный индекс — не украшение: три триггера (правка карточки,
правка профиля, ночная сверка) иначе наплодят соседних заявок на одно и то же
расхождение, и подтверждающий будет закрывать их по одной.

План: docs/superpowers/plans/2026-08-25-hr-identity-sync.md, задача 4.
"""
from __future__ import annotations

import pytest
from django.db import IntegrityError, transaction

from apps.hr.models import IdentityApprover, IdentityChangeRequest


@pytest.mark.django_db
def test_only_one_pending_request_per_employee(employee):
    IdentityChangeRequest.objects.create(
        employee=employee, user_id=1, status=IdentityChangeRequest.Status.PENDING,
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        IdentityChangeRequest.objects.create(
            employee=employee, user_id=1, status=IdentityChangeRequest.Status.PENDING,
        )


@pytest.mark.django_db
def test_closed_requests_do_not_block_a_new_one(employee):
    IdentityChangeRequest.objects.create(
        employee=employee, user_id=1, status=IdentityChangeRequest.Status.APPLIED,
    )
    IdentityChangeRequest.objects.create(
        employee=employee, user_id=1, status=IdentityChangeRequest.Status.REJECTED,
    )
    # закрытые не мешают завести новую открытую
    IdentityChangeRequest.objects.create(
        employee=employee, user_id=1, status=IdentityChangeRequest.Status.PENDING,
    )


@pytest.mark.django_db
def test_approver_is_singleton(db):
    IdentityApprover.objects.create(pk=1, user_id=5)
    with pytest.raises(IntegrityError), transaction.atomic():
        IdentityApprover.objects.create(pk=2, user_id=6)


@pytest.mark.django_db
def test_approver_row_may_be_empty(db):
    """Пустое назначение — законное состояние: подтверждает руководитель."""
    row = IdentityApprover.objects.create(pk=1, user_id=None)
    assert row.user_id is None
