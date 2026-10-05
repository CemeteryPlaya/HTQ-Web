"""Оптимистическая блокировка: E-CON-01 с именем и временем правки (§26.1)."""

from datetime import datetime, timezone as dt_timezone
from types import SimpleNamespace

import pytest

from apps.bpp.services.core.errors import check_version
from apps.users.models import User
from htqweb.errors import DomainError


@pytest.mark.django_db
def test_matching_version_passes():
    check_version(SimpleNamespace(version=3, updated_by=None, updated_at=None), 3)


@pytest.mark.django_db
def test_missing_expected_version_is_not_checked():
    check_version(SimpleNamespace(version=3, updated_by=None, updated_at=None), None)


@pytest.mark.django_db
def test_stale_version_names_who_and_when():
    user = User.objects.create(username="ivanov", email="i@htq.test", password="x",
                               last_name="Иванов", first_name="Алексей")
    obj = SimpleNamespace(version=4, updated_by=user.pk,
                          updated_at=datetime(2026, 9, 27, 9, 32, tzinfo=dt_timezone.utc))
    with pytest.raises(DomainError) as exc:
        check_version(obj, 3)
    assert (exc.value.code, exc.value.status) == ("E-CON-01", 409)
    assert "Иванов" in exc.value.message
    assert "14:32" in exc.value.message  # PLATFORM_TIME_ZONE Asia/Almaty = UTC+5
    assert exc.value.message.endswith("Обновите страницу и внесите их повторно.")
