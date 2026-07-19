"""Contract tests for ``/api/users/v1/{register,pending-registrations}/*``.

Mirrors ``services/user/app/api/v1/registration.py`` (the FastAPI original)
field for field, status for status, error string for error string — except
the dropped Redis pub/sub broadcasts (decision Р2, see
``apps.users.services.registration_service``'s module docstring). Tokens
are built with real ``htqweb.authn.jwt.issue_token_pair`` (no mocking).
"""

import pytest
from django.test import Client

from apps.users.models import User, UserStatus
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
def staff_user(db):
    u = User.objects.create(username="staffer", email="staffer@htq.test", password="x",
                            status=UserStatus.ACTIVE, is_staff=True)
    u.set_password("Staff1!Pass")
    u.save()
    return u


@pytest.fixture
def plain_user(db):
    u = User.objects.create(username="alice", email="alice@htq.test", password="x",
                            status=UserStatus.ACTIVE)
    u.set_password("S3cret!")
    u.save()
    return u


def _auth(user) -> dict:
    token = issue_token_pair(user)["access"]
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


# ── POST register/ ───────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_register_201_creates_pending_user(db):
    resp = Client().post(f"{BASE}/register/", data={
        "email": "New.User@htq.test", "password": "S3cret!Pass", "full_name": "Ivan Petrov",
    }, content_type="application/json")
    assert resp.status_code == 201
    body = resp.json()
    assert body["email"] == "new.user@htq.test"
    assert "id" in body
    assert body["message"] == "Registration submitted. Awaiting admin approval."

    user = User.objects.get(id=body["id"])
    assert user.status == UserStatus.PENDING
    assert user.username == "new.user@htq.test"
    assert user.email == "new.user@htq.test"
    assert user.first_name == "Ivan"
    assert user.last_name == "Petrov"
    assert user.display_name == "Ivan Petrov"
    # password hashed, not stored raw — and check_password works
    assert user.password != "S3cret!Pass"
    assert user.check_password("S3cret!Pass") is True


@pytest.mark.django_db
def test_register_full_name_single_word(db):
    resp = Client().post(f"{BASE}/register/", data={
        "email": "solo@htq.test", "password": "S3cret!Pass", "full_name": "Madonna",
    }, content_type="application/json")
    assert resp.status_code == 201
    user = User.objects.get(id=resp.json()["id"])
    assert user.first_name == "Madonna"
    assert user.last_name == ""


@pytest.mark.django_db
def test_register_full_name_extra_whitespace_and_words(db):
    """maxsplit=1 — only the first word becomes first_name, the rest
    (however many words) becomes last_name verbatim."""
    resp = Client().post(f"{BASE}/register/", data={
        "email": "triple@htq.test", "password": "S3cret!Pass",
        "full_name": "  Anna  Maria Ivanova  ",
    }, content_type="application/json")
    assert resp.status_code == 201
    user = User.objects.get(id=resp.json()["id"])
    assert user.first_name == "Anna"
    assert user.last_name == "Maria Ivanova"
    assert user.display_name == "Anna  Maria Ivanova"


@pytest.mark.django_db
def test_register_pending_user_cannot_login(db):
    resp = Client().post(f"{BASE}/register/", data={
        "email": "pending@htq.test", "password": "S3cret!Pass", "full_name": "Pending Guy",
    }, content_type="application/json")
    assert resp.status_code == 201

    login = Client().post(f"{BASE}/token/", data={
        "email": "pending@htq.test", "password": "S3cret!Pass",
    }, content_type="application/json")
    assert login.status_code == 401
    assert login.json() == {"detail": "Account is not activated"}


@pytest.mark.django_db
def test_register_duplicate_email_400(plain_user):
    """FastAPI source raises HTTPException(400, "Email already registered")
    — NOT 409."""
    resp = Client().post(f"{BASE}/register/", data={
        "email": "alice@htq.test", "password": "Whatever1!", "full_name": "Someone Else",
    }, content_type="application/json")
    assert resp.status_code == 400
    assert resp.json() == {"detail": "Email already registered"}


@pytest.mark.django_db
def test_register_duplicate_email_case_insensitive_400(plain_user):
    resp = Client().post(f"{BASE}/register/", data={
        "email": "ALICE@HTQ.TEST", "password": "Whatever1!", "full_name": "Someone Else",
    }, content_type="application/json")
    assert resp.status_code == 400
    assert resp.json() == {"detail": "Email already registered"}


# ── GET pending-registrations/ ───────────────────────────────────────────────


@pytest.mark.django_db
def test_list_pending_401_without_token(db):
    resp = Client().get(f"{BASE}/pending-registrations/")
    assert resp.status_code == 401


@pytest.mark.django_db
def test_list_pending_403_non_admin(plain_user):
    resp = Client().get(f"{BASE}/pending-registrations/", **_auth(plain_user))
    assert resp.status_code == 403


@pytest.mark.django_db
def test_list_pending_200_staff(staff_user, db):
    User.objects.create(username="p1", email="p1@htq.test", password="x",
                        status=UserStatus.PENDING, display_name="Pending One")
    resp = Client().get(f"{BASE}/pending-registrations/", **_auth(staff_user))
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    row = body[0]
    assert set(row) == {"id", "email", "username", "full_name", "date_joined"}
    assert row["email"] == "p1@htq.test"
    assert row["full_name"] == "Pending One"


@pytest.mark.django_db
def test_list_pending_200_superuser_excludes_non_pending(superuser, plain_user):
    User.objects.create(username="p2", email="p2@htq.test", password="x",
                        status=UserStatus.PENDING)
    resp = Client().get(f"{BASE}/pending-registrations/", **_auth(superuser))
    assert resp.status_code == 200
    emails = {row["email"] for row in resp.json()}
    assert emails == {"p2@htq.test"}
    assert "alice@htq.test" not in emails


# ── POST pending-registrations/{id}/approve/ ────────────────────────────────


@pytest.mark.django_db
def test_approve_401_without_token(db):
    pending = User.objects.create(username="p3", email="p3@htq.test", password="x",
                                  status=UserStatus.PENDING)
    resp = Client().post(f"{BASE}/pending-registrations/{pending.id}/approve/")
    assert resp.status_code == 401


@pytest.mark.django_db
def test_approve_403_non_admin(plain_user, db):
    pending = User.objects.create(username="p4", email="p4@htq.test", password="x",
                                  status=UserStatus.PENDING)
    resp = Client().post(f"{BASE}/pending-registrations/{pending.id}/approve/", **_auth(plain_user))
    assert resp.status_code == 403


@pytest.mark.django_db
def test_approve_204_activates_user(superuser, db):
    pending = User.objects.create(username="p5", email="p5@htq.test", password="x",
                                  status=UserStatus.PENDING)
    pending.set_password("S3cret!Pass")
    pending.save()

    resp = Client().post(f"{BASE}/pending-registrations/{pending.id}/approve/", **_auth(superuser))
    assert resp.status_code == 204
    assert resp.content == b""

    pending.refresh_from_db()
    assert pending.status == UserStatus.ACTIVE

    # now the user can actually authenticate
    login = Client().post(f"{BASE}/token/", data={
        "email": "p5@htq.test", "password": "S3cret!Pass",
    }, content_type="application/json")
    assert login.status_code == 200


@pytest.mark.django_db
def test_approve_404_unknown_id(superuser, db):
    resp = Client().post(f"{BASE}/pending-registrations/999999/approve/", **_auth(superuser))
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Pending registration not found"}


@pytest.mark.django_db
def test_approve_404_already_active_user(superuser, plain_user):
    """approve only matches status==PENDING — an ACTIVE user's id 404s,
    matching the source's combined id+status filter."""
    resp = Client().post(f"{BASE}/pending-registrations/{plain_user.id}/approve/", **_auth(superuser))
    assert resp.status_code == 404


# ── POST pending-registrations/{id}/reject/ ─────────────────────────────────


@pytest.mark.django_db
def test_reject_401_without_token(db):
    pending = User.objects.create(username="p6", email="p6@htq.test", password="x",
                                  status=UserStatus.PENDING)
    resp = Client().post(f"{BASE}/pending-registrations/{pending.id}/reject/")
    assert resp.status_code == 401


@pytest.mark.django_db
def test_reject_403_non_admin(plain_user, db):
    pending = User.objects.create(username="p7", email="p7@htq.test", password="x",
                                  status=UserStatus.PENDING)
    resp = Client().post(f"{BASE}/pending-registrations/{pending.id}/reject/", **_auth(plain_user))
    assert resp.status_code == 403


@pytest.mark.django_db
def test_reject_204_marks_rejected(staff_user, db):
    pending = User.objects.create(username="p8", email="p8@htq.test", password="x",
                                  status=UserStatus.PENDING)
    resp = Client().post(f"{BASE}/pending-registrations/{pending.id}/reject/", **_auth(staff_user))
    assert resp.status_code == 204
    pending.refresh_from_db()
    assert pending.status == UserStatus.REJECTED


@pytest.mark.django_db
def test_reject_404_unknown_id(staff_user, db):
    resp = Client().post(f"{BASE}/pending-registrations/999999/reject/", **_auth(staff_user))
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Pending registration not found"}


@pytest.mark.django_db
def test_reject_404_non_pending(staff_user, plain_user):
    resp = Client().post(f"{BASE}/pending-registrations/{plain_user.id}/reject/", **_auth(staff_user))
    assert resp.status_code == 404
