"""Task 2.6: django-admin must honor the service on/off switch.

``/django-admin/`` is mounted directly in htqweb/urls.py and never passes
through ServiceGateMiddleware (that only gates /api/... and /ws/... prefixes
— see htqweb/middleware/service_gate.py). Once domain models are registered
in the admin, a disabled app's data would otherwise stay fully readable and
writable through the admin UI. ServiceGatedAdminMixin (htqweb/admin_gate.py)
closes that at the ModelAdmin permission-hook layer.

``cms`` and ``users`` are seeded rows in the registry (migration-seeded, see
apps.core's registry migration) — always update_or_create, never create, to
avoid a duplicate-key IntegrityError against the seed row.
"""

import pytest
from django.core.cache import cache
from django.test import Client

from apps.core.models import ServiceStatus
from apps.core.services import service_enabled
from apps.users.models import User, UserStatus


@pytest.fixture
def superuser(db):
    u = User.objects.create(username="root-admin", email="root-admin@htq.test",
                            password="x", status=UserStatus.ACTIVE,
                            is_staff=True, is_superuser=True)
    u.set_password("Adm1n!Pass")
    u.save()
    return u


@pytest.fixture
def staff_user(db):
    """Active, is_staff=True, but NOT a superuser — decision Р1 baseline:
    User.has_perm/has_module_perms only pass for active superusers, so this
    user should see nothing in the admin regardless of any service state."""
    u = User.objects.create(username="staffer-admin", email="staffer-admin@htq.test",
                            password="x", status=UserStatus.ACTIVE, is_staff=True)
    u.set_password("Staff1!Pass")
    u.save()
    return u


def _client_as(user) -> Client:
    c = Client()
    c.force_login(user)
    return c


@pytest.mark.django_db
def test_cms_section_visible_on_index_when_enabled(superuser):
    ServiceStatus.objects.update_or_create(app_label="cms", defaults={"enabled": True})
    resp = _client_as(superuser).get("/django-admin/")
    assert resp.status_code == 200
    assert b"Cms" in resp.content or b"cms" in resp.content.lower()


@pytest.mark.django_db
def test_cms_section_absent_and_changelist_denied_when_disabled(superuser):
    ServiceStatus.objects.update_or_create(app_label="cms", defaults={"enabled": False})
    index = _client_as(superuser).get("/django-admin/")
    assert index.status_code == 200
    assert b"/django-admin/cms/news/" not in index.content

    resp = _client_as(superuser).get("/django-admin/cms/news/")
    # Measured directly (not assumed): Django's admin_view wrapper raises
    # PermissionDenied when a logged-in, admin-eligible user fails a
    # ModelAdmin permission check, which the exception middleware turns
    # into a plain 403 (not a redirect-to-login — that only happens for an
    # anonymous/non-staff user failing AdminSite.has_permission itself).
    assert resp.status_code == 403


@pytest.mark.django_db
def test_disabled_service_denies_add_change_delete_at_modeladmin_level(rf, superuser):
    """Test at the ModelAdmin permission-method level with a real request,
    per the task brief, in addition to the HTTP-level changelist check."""
    from django.contrib.admin.sites import site as admin_site

    from apps.cms.models import News

    ServiceStatus.objects.update_or_create(app_label="cms", defaults={"enabled": False})

    request = rf.get("/django-admin/cms/news/")
    request.user = superuser

    model_admin = admin_site._registry[News]
    assert model_admin.has_module_permission(request) is False
    assert model_admin.has_view_permission(request) is False
    assert model_admin.has_add_permission(request) is False
    assert model_admin.has_change_permission(request) is False
    assert model_admin.has_delete_permission(request) is False

    ServiceStatus.objects.update_or_create(app_label="cms", defaults={"enabled": True})
    # Bypassing the admin's own save_model here (direct ORM update), so bust
    # the cache by hand the way apps.core.admin.ServiceStatusAdmin.save_model
    # does — otherwise the 5s TTL from the read above still holds "disabled".
    cache.delete("svc-status:cms")
    assert model_admin.has_module_permission(request) is True
    assert model_admin.has_view_permission(request) is True
    assert model_admin.has_add_permission(request) is True
    assert model_admin.has_change_permission(request) is True
    assert model_admin.has_delete_permission(request) is True


@pytest.mark.django_db
def test_post_to_change_view_denied_when_disabled(superuser):
    from apps.cms.models import Category

    cat = Category.objects.create(slug="a", name="A")
    ServiceStatus.objects.update_or_create(app_label="cms", defaults={"enabled": False})

    resp = _client_as(superuser).post(
        f"/django-admin/cms/category/{cat.id}/change/",
        data={"slug": "b", "name": "B"},
    )
    assert resp.status_code == 403  # measured: see the GET-changelist test above
    cat.refresh_from_db()
    assert cat.slug == "a"  # write was blocked, not applied


@pytest.mark.django_db
def test_users_disabled_denies_users_but_cms_still_works(superuser):
    """Proves per-service isolation: disabling `users` must not affect `cms`."""
    ServiceStatus.objects.update_or_create(app_label="users", defaults={"enabled": False})
    ServiceStatus.objects.update_or_create(app_label="cms", defaults={"enabled": True})

    client = _client_as(superuser)

    users_resp = client.get("/django-admin/users/user/")
    assert users_resp.status_code == 403

    index = client.get("/django-admin/")
    assert b"/django-admin/users/user/" not in index.content
    assert b"/django-admin/cms/news/" in index.content

    cms_resp = client.get("/django-admin/cms/news/")
    assert cms_resp.status_code == 200


@pytest.mark.django_db
def test_service_status_admin_reachable_when_services_disabled(superuser):
    """Anti-lockout: ServiceStatus's own admin must stay reachable even when
    `cms`/`users`/anything else (including a row for its own app_label, if
    one ever existed) is disabled — otherwise there is no way to turn a
    service back on through the admin."""
    ServiceStatus.objects.update_or_create(app_label="cms", defaults={"enabled": False})
    ServiceStatus.objects.update_or_create(app_label="users", defaults={"enabled": False})

    client = _client_as(superuser)
    index = client.get("/django-admin/")
    assert b"/django-admin/core/servicestatus/" in index.content

    resp = client.get("/django-admin/core/servicestatus/")
    assert resp.status_code == 200


@pytest.mark.django_db
def test_saving_service_status_through_admin_busts_cache_immediately(superuser):
    row, _ = ServiceStatus.objects.update_or_create(
        app_label="cms", defaults={"enabled": True})
    # Prime the cache with the enabled value, the way a normal request would.
    assert service_enabled("cms") is True

    client = _client_as(superuser)
    resp = client.post(
        f"/django-admin/core/servicestatus/{row.id}/change/",
        data={
            "app_label": "cms",
            "enabled": "",  # unchecked checkbox -> False
            "message": row.message,
        },
    )
    assert resp.status_code == 302  # successful admin save redirects

    row.refresh_from_db()
    assert row.enabled is False
    # No 5s TTL wait: save_model must have busted svc-status:cms immediately.
    assert service_enabled("cms") is False


@pytest.mark.django_db
def test_non_superuser_staff_sees_nothing(staff_user):
    ServiceStatus.objects.update_or_create(app_label="cms", defaults={"enabled": True})
    client = _client_as(staff_user)
    index = client.get("/django-admin/")
    # Measured, not assumed: AdminSite.has_permission() only checks
    # is_active/is_staff (both True here), so the index itself renders 200 —
    # it's each ModelAdmin.has_module_permission() (which asks User.has_perm,
    # False for a non-superuser per decision Р1) that empties every section.
    assert index.status_code == 200
    assert b"/django-admin/cms/news/" not in index.content
    assert b"/django-admin/core/servicestatus/" not in index.content
    assert b"/django-admin/users/user/" not in index.content
