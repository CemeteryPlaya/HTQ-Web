"""Доставка — курьер, а не условие: заявка уже в БД (спека §11).

План: docs/superpowers/plans/2026-08-25-hr-identity-sync.md, задача 9.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from apps.hr.models import IdentityApprover, IdentityChangeRequest
from apps.hr.services import identity_request_service as svc


@pytest.mark.django_db
def test_notifies_resolved_approver(employee):
    IdentityApprover.objects.create(pk=1, user_id=321)

    with patch("apps.tasks.interface.push_notification") as push, \
            patch("apps.messenger.interface.dispatch_notification"):
        svc.capture(employee, {"first_name": "Иннокентий"}, actor_id=1)

    assert push.call_args.kwargs["recipient_id"] == 321
    assert push.call_args.kwargs["verb"] == "hr.identity_request"
    assert push.call_args.kwargs["target_type"] == "hr_identity_request"


@pytest.mark.django_db
def test_nightly_request_uses_its_own_verb(employee):
    """«Кто-то писал мимо API» и «HR попросил» требуют разной реакции."""
    IdentityApprover.objects.create(pk=1, user_id=321)

    with patch("apps.tasks.interface.push_notification") as push, \
            patch("apps.messenger.interface.dispatch_notification"):
        svc.capture(employee, {"first_name": "Иннокентий"}, actor_id=None,
                    source=IdentityChangeRequest.Source.NIGHTLY)

    assert push.call_args.kwargs["verb"] == "hr.identity_drift"


@pytest.mark.django_db
def test_bell_failure_does_not_lose_the_request(employee, fallback_log_mode):
    IdentityApprover.objects.create(pk=1, user_id=321)

    with patch("apps.tasks.interface.push_notification", side_effect=RuntimeError("boom")), \
            patch("apps.messenger.interface.dispatch_notification"):
        svc.capture(employee, {"first_name": "Иннокентий"}, actor_id=1)

    assert IdentityChangeRequest.objects.filter(employee=employee).exists()


@pytest.mark.django_db
def test_toast_failure_does_not_lose_the_request(employee, fallback_log_mode):
    IdentityApprover.objects.create(pk=1, user_id=321)

    with patch("apps.tasks.interface.push_notification"), \
            patch("apps.messenger.interface.dispatch_notification",
                  side_effect=RuntimeError("boom")):
        svc.capture(employee, {"first_name": "Иннокентий"}, actor_id=1)

    assert IdentityChangeRequest.objects.filter(employee=employee).exists()


@pytest.mark.django_db
def test_no_approver_is_expected_fallback(employee, fallback_log_mode):
    with patch("apps.tasks.interface.push_notification") as push:
        svc.capture(employee, {"first_name": "Иннокентий"}, actor_id=1)

    push.assert_not_called()
    # заявка всё равно записана — её увидит админ платформы
    assert IdentityChangeRequest.objects.filter(employee=employee).exists()
