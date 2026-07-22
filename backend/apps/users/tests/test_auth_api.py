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
def test_login_wrong_password_inactive_status_still_invalid_credentials(db):
    """auth_service.authenticate checks status BEFORE password (ported
    verbatim from the FastAPI original's obtain_token — see the docstring
    on authenticate()). So a non-ACTIVE user gets 'Account is not activated'
    regardless of whether the submitted password happens to be right OR
    wrong — the status check short-circuits before check_password runs."""
    u = User.objects.create(username="pending2", email="pending2@htq.test",
                            password="x", status=UserStatus.PENDING)
    u.set_password("S3cret!")
    u.save()
    resp = Client().post(f"{BASE}/token/", data={
        "email": "pending2@htq.test", "password": "totally-wrong",
    }, content_type="application/json")
    assert resp.status_code == 401
    assert resp.json() == {"detail": "Account is not activated"}


@pytest.mark.django_db
def test_failed_login_does_not_touch_last_login(active_user):
    assert active_user.last_login is None
    resp = Client().post(f"{BASE}/token/", data={
        "email": "alice@htq.test", "password": "wrong",
    }, content_type="application/json")
    assert resp.status_code == 401
    active_user.refresh_from_db()
    assert active_user.last_login is None


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
