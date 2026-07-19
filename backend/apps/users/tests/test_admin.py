"""FINDING 3 (Task 2.6 review): adding a User through django-admin must be
blocked.

``UserAdmin.exclude = ("password",)`` correctly keeps the password hash off
the form, but ``password`` is a required CharField with no default, so an
admin ADD would otherwise silently save ``password=""`` — an
unusable-password account with no warning. The chosen fix is to disable
adding users via this admin entirely: user creation already has a proper,
password-hashing home at ``POST /api/users/v1/admin/users/``.
"""

import pytest
from django.contrib.admin.sites import site as admin_site
from django.test import Client

from apps.users.models import User, UserStatus


@pytest.fixture
def superuser(db):
    u = User.objects.create(username="root-admin2", email="root-admin2@htq.test",
                            password="x", status=UserStatus.ACTIVE,
                            is_staff=True, is_superuser=True)
    u.set_password("Adm1n!Pass")
    u.save()
    return u


@pytest.mark.django_db
def test_user_admin_denies_add_permission(rf, superuser):
    from apps.users.models import User as UserModel

    request = rf.get("/django-admin/users/user/add/")
    request.user = superuser

    model_admin = admin_site._registry[UserModel]
    assert model_admin.has_add_permission(request) is False


@pytest.mark.django_db
def test_user_admin_add_view_denied_over_http(superuser):
    client = Client()
    client.force_login(superuser)

    resp = client.get("/django-admin/users/user/add/")
    assert resp.status_code == 403

    before = User.objects.count()
    resp = client.post("/django-admin/users/user/add/", data={
        "username": "new-guy", "email": "new-guy@htq.test",
        "status": UserStatus.ACTIVE,
    })
    assert resp.status_code == 403
    assert User.objects.count() == before  # nothing was created
