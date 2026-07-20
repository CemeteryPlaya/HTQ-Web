"""TDD for R3 remediation — ``apps/users/services/audit.py::record_action``
wired into the identity domain's six privileged mutation points.

Mirrors the assertion style of ``apps/cms/tests/test_news_api.py``
(``AuditLog.objects.get(action=...)``), collected in its own file per the R3
task brief rather than embedded across the existing admin/registration API
test files. Tokens are built with real ``htqweb.authn.jwt.issue_token_pair``
against real DB rows — no mocking.
"""

import logging

import pytest
from django.test import Client

from apps.users.models import AuditLog, User, UserStatus
from htqweb.authn.jwt import issue_token_pair

BASE = "/api/users/v1"


@pytest.fixture
def superuser(db):
    u = User.objects.create(username="root", email="root@htq.test", password="x",
                            status=UserStatus.ACTIVE, is_superuser=True)
    u.set_password("Adm1n!Pass")
    u.save()
    return u


@pytest.fixture
def plain_user(db):
    u = User.objects.create(username="alice", email="alice@htq.test", password="x",
                            status=UserStatus.ACTIVE, first_name="Alice", last_name="Smith")
    u.set_password("S3cret!")
    u.save()
    return u


def _auth(user) -> dict:
    token = issue_token_pair(user)["access"]
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


# ── admin create user -> "user.created" ──────────────────────────────────────


@pytest.mark.django_db
def test_admin_create_user_writes_audit_log(superuser, db):
    resp = Client().post(f"{BASE}/admin/users/", data={
        "username": "newbie", "email": "newbie@htq.test", "password": "Passw0rd!",
    }, content_type="application/json", **_auth(superuser))
    assert resp.status_code == 201
    new_id = resp.json()["id"]

    log = AuditLog.objects.get(action="user.created")
    assert log.resource_type == "User"
    assert log.resource_id == str(new_id)
    assert log.user_id == superuser.id
    assert log.changes["username"] == "newbie"
    assert log.changes["email"] == "newbie@htq.test"


@pytest.mark.django_db
def test_admin_create_user_audit_never_contains_password(superuser, db):
    resp = Client().post(f"{BASE}/admin/users/", data={
        "username": "newbie2", "email": "newbie2@htq.test",
        "password": "Passw0rd!Secret",
    }, content_type="application/json", **_auth(superuser))
    assert resp.status_code == 201

    log = AuditLog.objects.get(action="user.created")
    assert "password" not in log.changes
    assert "password_hash" not in log.changes
    dumped = str(log.changes)
    assert "Passw0rd!Secret" not in dumped

    user = User.objects.get(username="newbie2")
    assert user.password not in dumped  # the stored hash never lands either


@pytest.mark.django_db
def test_admin_create_user_audit_captures_request_metadata(superuser, db):
    resp = Client().post(
        f"{BASE}/admin/users/",
        data={"username": "meta1", "email": "meta1@htq.test", "password": "Passw0rd!"},
        content_type="application/json",
        HTTP_USER_AGENT="pytest-agent/1.0",
        **_auth(superuser),
    )
    assert resp.status_code == 201
    log = AuditLog.objects.get(action="user.created")
    assert log.user_agent == "pytest-agent/1.0"
    assert log.ip_address  # Django test client sets REMOTE_ADDR (127.0.0.1)


# ── audit write failure must be non-fatal (review fix-pass on R3) ───────────


@pytest.mark.django_db
def test_admin_create_user_audit_write_failure_is_non_fatal(superuser, db, monkeypatch, caplog):
    """R3 wired ``audit.record_action`` into every privileged admin mutation,
    guaranteeing the write is non-fatal (guard now lives in ``apps.users.
    services.audit.record_action`` itself — see its docstring). This proves
    that guarantee end-to-end: force ``AuditLog.objects.create`` to raise,
    perform a real admin create over HTTP, and assert (a) the endpoint still
    returns 201, (b) the user was actually created (the mutation committed),
    and (c) the failure was logged loudly rather than disappearing silently.

    Confirmed RED: temporarily removing the ``try/except`` around
    ``AuditLog.objects.create`` in ``apps.users.services.audit.record_action``
    makes this test fail with the injected ``RuntimeError`` propagating out
    as a 500 (see the R3 fix-pass report for the transcript).
    """

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated audit DB failure")

    monkeypatch.setattr(AuditLog.objects, "create", _boom)

    with caplog.at_level(logging.ERROR, logger="apps.users.services.audit"):
        resp = Client().post(f"{BASE}/admin/users/", data={
            "username": "resilient", "email": "resilient@htq.test", "password": "Passw0rd!",
        }, content_type="application/json", **_auth(superuser))

    assert resp.status_code == 201
    assert User.objects.filter(username="resilient").exists()
    # The audit row itself is the thing that failed to write — it must not
    # exist, but that must not have taken the mutation down with it.
    assert not AuditLog.objects.filter(action="user.created").exists()
    assert any(
        "audit record_action failed" in record.getMessage()
        for record in caplog.records
    )


# ── admin update user -> "user.updated" ──────────────────────────────────────


@pytest.mark.django_db
def test_admin_update_user_writes_audit_log_with_privilege_diff(superuser, plain_user):
    resp = Client().patch(f"{BASE}/admin/users/{plain_user.id}/", data={
        "is_staff": True, "status": "suspended",
    }, content_type="application/json", **_auth(superuser))
    assert resp.status_code == 200

    log = AuditLog.objects.get(action="user.updated")
    assert log.resource_type == "User"
    assert log.resource_id == str(plain_user.id)
    assert log.user_id == superuser.id
    assert log.changes["is_staff"] == {"old": False, "new": True}
    assert log.changes["status"] == {"old": "active", "new": "suspended"}


@pytest.mark.django_db
def test_admin_update_user_diff_excludes_unchanged_fields(superuser, plain_user):
    """A field sent with the SAME value it already had must not show up in
    the diff — the audit ``changes`` payload records what actually changed,
    not the raw request body."""
    resp = Client().patch(f"{BASE}/admin/users/{plain_user.id}/", data={
        "first_name": "Alice",  # unchanged
        "phone": "+7 700 000 00 00",  # changed (was "")
    }, content_type="application/json", **_auth(superuser))
    assert resp.status_code == 200

    log = AuditLog.objects.get(action="user.updated")
    assert "phone" in log.changes
    assert "first_name" not in log.changes


@pytest.mark.django_db
def test_admin_update_user_audit_never_contains_password(superuser, plain_user):
    """``AdminUserUpdateRequest`` has no ``password`` field (password changes
    go through set-password) — Pydantic silently drops unknown keys (no
    ``extra="forbid"``), so this exercises the REAL request path: inject a
    stray ``"password"`` key into the PATCH body and assert (a) it's absent
    from ``AdminUserUpdateRequest.model_fields`` (the static guarantee), and
    (b) the live audit ``changes`` diff contains no password/password_hash
    key, and (c) the injected value was never applied — the user's password
    hash is unchanged and doesn't verify against it.
    """
    from apps.users.schemas import AdminUserUpdateRequest

    assert "password" not in AdminUserUpdateRequest.model_fields

    old_hash = plain_user.password
    resp = Client().patch(f"{BASE}/admin/users/{plain_user.id}/", data={
        "phone": "+7 700 111 22 33",
        "password": "InjectedPassw0rd!",
    }, content_type="application/json", **_auth(superuser))
    assert resp.status_code == 200

    log = AuditLog.objects.get(action="user.updated")
    assert "phone" in log.changes  # the real change is still recorded
    assert "password" not in log.changes
    assert "password_hash" not in log.changes
    assert "InjectedPassw0rd!" not in str(log.changes)

    plain_user.refresh_from_db()
    assert plain_user.password == old_hash  # stray field ignored, not applied
    assert not plain_user.check_password("InjectedPassw0rd!")


# ── admin set-password -> "user.password_set" ────────────────────────────────


@pytest.mark.django_db
def test_admin_set_password_writes_audit_log(superuser, plain_user):
    resp = Client().post(f"{BASE}/admin/users/{plain_user.id}/set-password/", data={
        "new_password": "NewPassw0rd!", "must_change_password": False,
    }, content_type="application/json", **_auth(superuser))
    assert resp.status_code == 200

    log = AuditLog.objects.get(action="user.password_set")
    assert log.resource_type == "User"
    assert log.resource_id == str(plain_user.id)
    assert log.user_id == superuser.id
    assert log.changes == {"must_change_password": False}


@pytest.mark.django_db
def test_admin_set_password_audit_never_contains_password(superuser, plain_user):
    resp = Client().post(f"{BASE}/admin/users/{plain_user.id}/set-password/", data={
        "new_password": "SuperSecretPassw0rd!",
    }, content_type="application/json", **_auth(superuser))
    assert resp.status_code == 200

    log = AuditLog.objects.get(action="user.password_set")
    assert "new_password" not in log.changes
    assert "password" not in log.changes
    dumped = str(log.changes)
    assert "SuperSecretPassw0rd!" not in dumped

    # No plaintext/hash of the new password anywhere in ANY audit row
    # written during this test (belt-and-suspenders on top of the field
    # check above).
    for row in AuditLog.objects.all():
        assert "SuperSecretPassw0rd!" not in str(row.changes)


# ── admin delete (soft-delete -> SUSPENDED) -> "user.suspended" ──────────────


@pytest.mark.django_db
def test_admin_delete_user_writes_audit_log(superuser, plain_user):
    resp = Client().delete(f"{BASE}/admin/users/{plain_user.id}/", **_auth(superuser))
    assert resp.status_code == 204

    log = AuditLog.objects.get(action="user.suspended")
    assert log.resource_type == "User"
    assert log.resource_id == str(plain_user.id)
    assert log.user_id == superuser.id
    # ``_admin_delete_user`` writes a static resulting-state dict (not a
    # before/after diff) — acceptable for an unconditional SUSPEND, but the
    # shape itself was previously unasserted.
    assert log.changes == {
        "status": "suspended", "is_staff": False, "is_superuser": False,
    }


# ── registration approve -> "registration.approved" ──────────────────────────


@pytest.mark.django_db
def test_approve_registration_writes_audit_log(superuser, db):
    pending = User.objects.create(username="p1", email="p1@htq.test", password="x",
                                  status=UserStatus.PENDING)
    resp = Client().post(f"{BASE}/pending-registrations/{pending.id}/approve/", **_auth(superuser))
    assert resp.status_code == 204

    log = AuditLog.objects.get(action="registration.approved")
    assert log.resource_type == "User"
    assert log.resource_id == str(pending.id)
    assert log.user_id == superuser.id


# ── registration reject -> "registration.rejected" ───────────────────────────


@pytest.mark.django_db
def test_reject_registration_writes_audit_log(superuser, db):
    pending = User.objects.create(username="p2", email="p2@htq.test", password="x",
                                  status=UserStatus.PENDING)
    resp = Client().post(f"{BASE}/pending-registrations/{pending.id}/reject/", **_auth(superuser))
    assert resp.status_code == 204

    log = AuditLog.objects.get(action="registration.rejected")
    assert log.resource_type == "User"
    assert log.resource_id == str(pending.id)
    assert log.user_id == superuser.id
