"""``apps.users.interface.active_user_ids`` — адресаты ежедневной сводки
центра уведомлений: все с действующей учёткой, без фильтра по флагам."""

from __future__ import annotations

import pytest

from apps.users import interface
from apps.users.models import User, UserStatus


def _user(username: str, *, status: str = UserStatus.ACTIVE, **flags) -> User:
    return User.objects.create(username=username, email=f"{username}@htq.test",
                               password="x", status=status, **flags)


@pytest.mark.django_db
def test_only_active_accounts_in_id_order():
    first = _user("first")
    _user("pending", status=UserStatus.PENDING)
    root = _user("root", is_superuser=True, is_staff=True)
    assert interface.active_user_ids() == sorted([first.id, root.id])
