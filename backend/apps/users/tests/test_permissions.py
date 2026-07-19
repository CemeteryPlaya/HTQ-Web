"""has_perm/has_module_perms after dropping PermissionsMixin (decision Р1).

No Django groups/permissions backing these anymore — the minimal replacement
is just "active superuser passes, everyone else doesn't" (task 2.6 builds
the real admin gate on top of this).
"""

import pytest

from apps.users.models import User, UserStatus


@pytest.mark.django_db
def test_active_superuser_has_perm():
    u = User.objects.create(username="su", email="su@htq.test", password="x",
                            status=UserStatus.ACTIVE, is_superuser=True)
    assert u.has_perm("anything.at_all") is True
    assert u.has_module_perms("any_app") is True


@pytest.mark.django_db
def test_inactive_superuser_has_no_perm():
    u = User.objects.create(username="su2", email="su2@htq.test", password="x",
                            status=UserStatus.PENDING, is_superuser=True)
    assert u.has_perm("anything.at_all") is False
    assert u.has_module_perms("any_app") is False


@pytest.mark.django_db
def test_active_staff_non_superuser_has_no_perm():
    u = User.objects.create(username="staff1", email="staff1@htq.test", password="x",
                            status=UserStatus.ACTIVE, is_staff=True, is_superuser=False)
    assert u.has_perm("anything.at_all") is False
    assert u.has_module_perms("any_app") is False
