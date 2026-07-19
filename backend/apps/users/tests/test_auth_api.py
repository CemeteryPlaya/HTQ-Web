"""Contract tests for ``/api/users/v1/{token,token/refresh,admin-session}/*``.

Mirrors ``services/user/app/api/v1/auth.py`` (the FastAPI original) field for
field, status for status, error string for error string. Tokens for the
refresh/decode assertions are built with real ``jwt.encode``/``htqweb.authn``
(no mocking of ``decode_token``) — same style as
``apps/cms/tests/test_contact_requests_api.py``.
"""

import jwt as pyjwt
import pytest
from django.conf import settings
from django.test import Client

from apps.users.models import User, UserStatus
from htqweb.authn.jwt import decode_token, issue_token_pair

BASE = "/api/users/v1"


@pytest.fixture
def active_user(db):
    u = User.objects.create(username="alice", email="alice@htq.test", password="x",
                            status=UserStatus.ACTIVE)
    u.set_password("S3cret!")
    u.save()
    return u


@pytest.fixture
def superuser(db):
    u = User.objects.create(username="root", email="root@htq.test", password="x",
                            status=UserStatus.ACTIVE, is_superuser=True)
    u.set_password("Adm1n!Pass")
    u.save()
    return u


@pytest.fixture
def staff_user(db):
    u = User.objects.create(username="staffer", email="staffer@htq.test", password="x",
                            status=UserStatus.ACTIVE, is_staff=True)
    u.set_password("Staff1!Pass")
    u.save()
    return u


# ── POST token/ — login ──────────────────────────────────────────────────────


@pytest.mark.django_db
def test_login_by_email_200_with_all_three_fields(active_user):
    resp = Client().post(f"{BASE}/token/", data={
        "email": "alice@htq.test", "password": "S3cret!",
    }, content_type="application/json")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"access", "refresh", "token_type"}
    assert body["token_type"] == "Bearer"
    assert body["access"]
    assert body["refresh"]


@pytest.mark.django_db
def test_login_by_username_200(active_user):
    resp = Client().post(f"{BASE}/token/", data={
        "email": "alice", "password": "S3cret!",
    }, content_type="application/json")
    assert resp.status_code == 200
    body = resp.json()
    assert body["token_type"] == "Bearer"


@pytest.mark.django_db
def test_login_wrong_password_401_invalid_credentials(active_user):
    resp = Client().post(f"{BASE}/token/", data={
        "email": "alice@htq.test", "password": "wrong",
    }, content_type="application/json")
    assert resp.status_code == 401
    assert resp.json() == {"detail": "Invalid credentials"}


@pytest.mark.django_db
def test_login_unknown_user_401_invalid_credentials(db):
    resp = Client().post(f"{BASE}/token/", data={
        "email": "nobody@htq.test", "password": "whatever",
    }, content_type="application/json")
    assert resp.status_code == 401
    assert resp.json() == {"detail": "Invalid credentials"}


@pytest.mark.django_db
@pytest.mark.parametrize("status", [UserStatus.PENDING, UserStatus.SUSPENDED])
def test_login_correct_password_inactive_status_401_not_activated(db, status):
    u = User.objects.create(username="pending1", email="pending1@htq.test",
                            password="x", status=status)
    u.set_password("S3cret!")
    u.save()
    resp = Client().post(f"{BASE}/token/", data={
        "email": "pending1@htq.test", "password": "S3cret!",
    }, content_type="application/json")
    assert resp.status_code == 401
    assert resp.json() == {"detail": "Account is not activated"}


@pytest.mark.django_db
def test_login_updates_last_login(active_user):
    assert active_user.last_login is None
    resp = Client().post(f"{BASE}/token/", data={
        "email": "alice@htq.test", "password": "S3cret!",
    }, content_type="application/json")
    assert resp.status_code == 200
    active_user.refresh_from_db()
    assert active_user.last_login is not None


@pytest.mark.django_db
def test_login_issued_access_token_decodes_with_full_claim_set(active_user):
    resp = Client().post(f"{BASE}/token/", data={
        "email": "alice@htq.test", "password": "S3cret!",
    }, content_type="application/json")
    access = resp.json()["access"]
    payload = decode_token(access)
    assert payload.user_id == active_user.id
    assert payload.username == active_user.username
    assert payload.email == active_user.email
    assert payload.token_type == "access"
    assert payload.is_staff is False
    assert payload.is_superuser is False
    assert payload.is_admin is False


# ── POST token/refresh/ ──────────────────────────────────────────────────────


@pytest.mark.django_db
def test_refresh_with_real_refresh_token_200_new_access(active_user):
    pair = issue_token_pair(active_user)
    resp = Client().post(f"{BASE}/token/refresh/", data={
        "refresh": pair["refresh"],
    }, content_type="application/json")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"access", "token_type"}
    assert body["token_type"] == "Bearer"
    new_payload = decode_token(body["access"])
    assert new_payload.user_id == active_user.id
    assert new_payload.token_type == "access"


@pytest.mark.django_db
def test_refresh_with_access_token_401(active_user):
    pair = issue_token_pair(active_user)
    resp = Client().post(f"{BASE}/token/refresh/", data={
        "refresh": pair["access"],
    }, content_type="application/json")
    assert resp.status_code == 401
    assert "detail" in resp.json()


@pytest.mark.django_db
def test_refresh_with_garbage_401(db):
    resp = Client().post(f"{BASE}/token/refresh/", data={
        "refresh": "not-a-jwt-at-all",
    }, content_type="application/json")
    assert resp.status_code == 401
    assert "detail" in resp.json()


# ── POST admin-session/login ─────────────────────────────────────────────────


@pytest.mark.django_db
def test_admin_login_superuser_303_sets_cookie_and_location(superuser):
    resp = Client().post(f"{BASE}/admin-session/login", data={
        "username": "root", "password": "Adm1n!Pass",
    })
    assert resp.status_code == 303
    assert resp["Location"] == "/sqladmin/"
    assert "admin_session" in resp.cookies
    cookie = resp.cookies["admin_session"]
    assert cookie["httponly"] is True
    assert cookie["samesite"] == "Lax"
    assert cookie["path"] == "/"
    # cookie value decodes to a valid, elevated access token
    payload = decode_token(cookie.value)
    assert payload.user_id == superuser.id
    assert payload.is_elevated is True


@pytest.mark.django_db
def test_admin_login_staff_303(staff_user):
    resp = Client().post(f"{BASE}/admin-session/login", data={
        "username": "staffer", "password": "Staff1!Pass", "next": "/sqladmin/cms/",
    })
    assert resp.status_code == 303
    assert resp["Location"] == "/sqladmin/cms/"


@pytest.mark.django_db
def test_admin_login_non_elevated_active_user_rejected(active_user):
    """Source (services/user/app/api/v1/auth.py::admin_login) raises
    HTTPException(403, "Not an admin user") for an active, correctly
    authenticated user who is neither is_staff nor is_superuser."""
    resp = Client().post(f"{BASE}/admin-session/login", data={
        "username": "alice", "password": "S3cret!",
    })
    assert resp.status_code == 403
    assert resp.json() == {"detail": "Not an admin user"}
    assert "admin_session" not in resp.cookies or not resp.cookies["admin_session"].value


@pytest.mark.django_db
def test_admin_login_unknown_user_401_invalid_credentials(db):
    resp = Client().post(f"{BASE}/admin-session/login", data={
        "username": "ghost", "password": "whatever",
    })
    assert resp.status_code == 401
    assert resp.json() == {"detail": "Invalid credentials"}


@pytest.mark.django_db
def test_admin_login_superuser_wrong_password_401_invalid_credentials(superuser):
    resp = Client().post(f"{BASE}/admin-session/login", data={
        "username": "root", "password": "wrong",
    })
    assert resp.status_code == 401
    assert resp.json() == {"detail": "Invalid credentials"}


# ── POST admin-session/logout ────────────────────────────────────────────────


@pytest.mark.django_db
def test_admin_logout_200_and_clears_cookie(db):
    resp = Client().post(f"{BASE}/admin-session/logout")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    cookie = resp.cookies["admin_session"]
    assert cookie.value == ""
    assert cookie["max-age"] == 0
