"""R2 remediation: apps/media_files/admin.py must honor the service on/off
switch, same as cms/users already do (apps/core/tests/test_admin_gate.py).

Before R2 there was no admin.py at all here, so there was nothing for
ServiceGatedAdminMixin to even sit on — apps.core.tests.test_invariants'
``test_every_domain_model_admin_has_service_gate_mixin`` carried
``media_files`` in its ``_KNOWN_UNREGISTERED`` allow-list as a documented
gap. This file is the gate-behavior proof that closing that gap actually
works end to end (index visibility + changelist GET), not just "the mixin
is present on the class".

``media`` is a seeded ``ServiceStatus`` row (migration-seeded, like
``cms``/``users``) — always ``update_or_create``, never ``create``, to avoid
a duplicate-key IntegrityError against the seed row.
"""

import pytest
from django.core.cache import cache
from django.test import Client

from apps.core.models import ServiceStatus
from apps.users.models import User, UserStatus


@pytest.fixture
def superuser(db):
    u = User.objects.create(username="media-admin", email="media-admin@htq.test",
                            password="x", status=UserStatus.ACTIVE,
                            is_staff=True, is_superuser=True)
    u.set_password("Adm1n!Pass")
    u.save()
    return u


def _client_as(user) -> Client:
    c = Client()
    c.force_login(user)
    return c


@pytest.mark.django_db
def test_media_section_visible_on_index_when_enabled(superuser):
    ServiceStatus.objects.update_or_create(app_label="media", defaults={"enabled": True})
    resp = _client_as(superuser).get("/django-admin/")
    assert resp.status_code == 200
    assert b"/django-admin/media_files/filemetadata/" in resp.content


@pytest.mark.django_db
def test_filemetadata_changelist_reachable_when_media_enabled(superuser):
    ServiceStatus.objects.update_or_create(app_label="media", defaults={"enabled": True})
    resp = _client_as(superuser).get("/django-admin/media_files/filemetadata/")
    assert resp.status_code == 200


@pytest.mark.django_db
def test_filemetadata_changelist_denied_when_media_disabled(superuser):
    ServiceStatus.objects.update_or_create(app_label="media", defaults={"enabled": False})
    index = _client_as(superuser).get("/django-admin/")
    assert index.status_code == 200
    assert b"/django-admin/media_files/filemetadata/" not in index.content

    resp = _client_as(superuser).get("/django-admin/media_files/filemetadata/")
    # Same measured contract as cms/users: PermissionDenied from the
    # ModelAdmin permission hooks turns into a plain 403 for an
    # already-admin-eligible (staff+superuser) user — not a redirect.
    assert resp.status_code == 403


@pytest.mark.django_db
def test_filevariant_and_auditlog_changelists_also_gated(superuser):
    """The other two registered models must be gated too, not just the one
    used as the representative example above."""
    ServiceStatus.objects.update_or_create(app_label="media", defaults={"enabled": False})
    cache.delete("svc-status:media")
    client = _client_as(superuser)
    assert client.get("/django-admin/media_files/filevariant/").status_code == 403
    assert client.get("/django-admin/media_files/auditlog/").status_code == 403

    ServiceStatus.objects.update_or_create(app_label="media", defaults={"enabled": True})
    cache.delete("svc-status:media")
    client = _client_as(superuser)
    assert client.get("/django-admin/media_files/filevariant/").status_code == 200
    assert client.get("/django-admin/media_files/auditlog/").status_code == 200


@pytest.mark.django_db
def test_filemetadata_and_filevariant_are_read_only_when_media_enabled(superuser):
    """Decision Д4: FileMetadata/FileVariant admin is view-only — add and
    change are unconditionally refused (independent of the service gate),
    since rows come from the upload pipeline and a hand-authored/edited row
    would desync from actual storage."""
    ServiceStatus.objects.update_or_create(app_label="media", defaults={"enabled": True})
    client = _client_as(superuser)

    add_meta = client.get("/django-admin/media_files/filemetadata/add/")
    assert add_meta.status_code == 403
    add_variant = client.get("/django-admin/media_files/filevariant/add/")
    assert add_variant.status_code == 403


@pytest.mark.django_db
def test_auditlog_is_add_only_denied_when_media_enabled(superuser):
    """AuditLog rows are written by code only — mirrors
    apps.cms.admin.AuditLogAdmin's has_add_permission."""
    ServiceStatus.objects.update_or_create(app_label="media", defaults={"enabled": True})
    resp = _client_as(superuser).get("/django-admin/media_files/auditlog/add/")
    assert resp.status_code == 403
