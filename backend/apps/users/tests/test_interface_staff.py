"""Tests for ``apps.users.interface.staff_user_ids`` (block L, task 2).

The one consumer is ``manage.py access_backfill_services_admin``: it needs
exactly the people the pre-gate admin screens (media/conference/messenger/
mail/cms/approvals) let in by ``is_staff`` alone — staff, not superuser, with
an active account. Three cases per the task brief: staff yes, superuser no,
inactive no.
"""

from __future__ import annotations

import pytest

from apps.users import interface
from apps.users.models import User, UserStatus


def _user(username: str, *, staff: bool = False, superuser: bool = False,
          status: str = UserStatus.ACTIVE) -> User:
    return User.objects.create(
        username=username, email=f"{username}@htq.test", password="x",
        status=status, is_staff=staff, is_superuser=superuser,
    )


@pytest.mark.django_db
def test_staff_member_is_included():
    staff = _user("staffer", staff=True)

    assert interface.staff_user_ids() == [staff.id]


@pytest.mark.django_db
def test_superuser_is_excluded():
    _user("root", staff=True, superuser=True)

    assert interface.staff_user_ids() == []


@pytest.mark.django_db
def test_inactive_staff_is_excluded():
    _user("gone", staff=True, status=UserStatus.SUSPENDED)

    assert interface.staff_user_ids() == []
