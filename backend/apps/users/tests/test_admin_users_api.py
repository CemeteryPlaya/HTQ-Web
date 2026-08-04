"""Contract tests for ``/api/users/v1/admin/users/*``.

Mirrors ``services/user/app/api/v1/admin.py`` (the FastAPI original) field
for field, status for status, error string for error string — except the
dropped Redis pub/sub broadcasts, the S2S mailbox-archive call in DELETE,
and Mailcow mailbox provisioning in POST (decisions Р2/Р3, see
``apps.users.services.admin_service``'s module docstring). Tokens are built
with real ``htqweb.authn.jwt.issue_token_pair`` (no mocking).
"""

import pytest
from django.test import Client, override_settings

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
                            status=UserStatus.ACTIVE, first_name="Alice", last_name="Smith")
    u.set_password("S3cret!")
    u.save()
    return u


def _auth(user) -> dict:
    token = issue_token_pair(user)["access"]
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


ADMIN_RESPONSE_FIELDS = {
    "id", "username", "email", "first_name", "last_name", "firstName", "lastName",
    "patronymic", "display_name", "bio", "phone", "avatar_url", "avatarUrl",
    "settings", "roles", "status", "is_staff", "is_superuser", "must_change_password",
    "date_joined", "last_login", "created_at", "updated_at",
}

# POST admin/users/ returns AdminUserCreatedResponse — AdminUserResponse plus
# the mailbox-provisioning outcome fields (always present: ``mailbox`` is
# always null in this port, ``mailbox_error`` set iff create_mailbox=True).
ADMIN_CREATED_RESPONSE_FIELDS = ADMIN_RESPONSE_FIELDS | {"mailbox", "mailbox_error"}


# ── GET admin/users/ ──────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_list_users_401_without_token(db):
    resp = Client().get(f"{BASE}/admin/users/")
    assert resp.status_code == 401


@pytest.mark.django_db
def test_list_users_403_non_admin(plain_user):
    resp = Client().get(f"{BASE}/admin/users/", **_auth(plain_user))
    assert resp.status_code == 403


@pytest.mark.django_db
def test_list_users_200_superuser(superuser, plain_user):
    resp = Client().get(f"{BASE}/admin/users/", **_auth(superuser))
    assert resp.status_code == 200
    body = resp.json()
    usernames = {row["username"] for row in body}
    assert {"root", "alice"} <= usernames
    row = next(r for r in body if r["username"] == "alice")
    assert set(row) == ADMIN_RESPONSE_FIELDS
    assert row["roles"] == ["user"]
    assert row["first_name"] == "Alice"
    assert row["firstName"] == "Alice"


@pytest.mark.django_db
def test_list_users_roles(superuser, staff_user, plain_user):
    resp = Client().get(f"{BASE}/admin/users/", **_auth(superuser))
    body = resp.json()
    by_username = {r["username"]: r for r in body}
    assert by_username["root"]["roles"] == ["admin"]
    assert by_username["staffer"]["roles"] == ["staff"]
    assert by_username["alice"]["roles"] == ["user"]


# ── POST admin/users/ ─────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_create_user_401_without_token(db):
    resp = Client().post(f"{BASE}/admin/users/", data={
        "username": "newbie", "email": "newbie@htq.test", "password": "Passw0rd!",
    }, content_type="application/json")
    assert resp.status_code == 401


@pytest.mark.django_db
def test_create_user_403_non_admin(plain_user):
    resp = Client().post(f"{BASE}/admin/users/", data={
        "username": "newbie", "email": "newbie@htq.test", "password": "Passw0rd!",
    }, content_type="application/json", **_auth(plain_user))
    assert resp.status_code == 403


@pytest.mark.django_db
def test_create_user_201_defaults(superuser, db):
    resp = Client().post(f"{BASE}/admin/users/", data={
        "username": "newbie", "email": "Newbie@Htq.Test", "password": "Passw0rd!",
    }, content_type="application/json", **_auth(superuser))
    assert resp.status_code == 201
    body = resp.json()
    assert set(body) == ADMIN_CREATED_RESPONSE_FIELDS
    assert body["email"] == "newbie@htq.test"
    assert body["status"] == "active"
    assert body["is_staff"] is False
    assert body["is_superuser"] is False
    assert body["must_change_password"] is True

    user = User.objects.get(username="newbie")
    assert user.status == UserStatus.ACTIVE
    assert user.check_password("Passw0rd!") is True
    assert user.password != "Passw0rd!"


@pytest.mark.django_db
def test_create_user_201_explicit_fields(superuser, db):
    resp = Client().post(f"{BASE}/admin/users/", data={
        "username": "manager1", "email": "manager1@htq.test", "password": "Passw0rd!",
        "first_name": "Ivan", "last_name": "Petrov", "status": "pending",
        "is_staff": True, "must_change_password": False,
    }, content_type="application/json", **_auth(superuser))
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "pending"
    assert body["is_staff"] is True
    assert body["must_change_password"] is False
    assert body["display_name"] == "Ivan Petrov"


@pytest.mark.django_db
def test_create_user_duplicate_email_400(superuser, plain_user):
    resp = Client().post(f"{BASE}/admin/users/", data={
        "username": "someoneelse", "email": "alice@htq.test", "password": "Passw0rd!",
    }, content_type="application/json", **_auth(superuser))
    assert resp.status_code == 400
    assert resp.json() == {"detail": "Email already in use"}


@pytest.mark.django_db
def test_create_user_duplicate_username_400(superuser, plain_user):
    resp = Client().post(f"{BASE}/admin/users/", data={
        "username": "alice", "email": "different@htq.test", "password": "Passw0rd!",
    }, content_type="application/json", **_auth(superuser))
    assert resp.status_code == 400
    assert resp.json() == {"detail": "Username already in use"}


@pytest.mark.django_db
def test_create_user_invalid_status_400(superuser, db):
    resp = Client().post(f"{BASE}/admin/users/", data={
        "username": "ghost", "email": "ghost@htq.test", "password": "Passw0rd!",
        "status": "not-a-status",
    }, content_type="application/json", **_auth(superuser))
    assert resp.status_code == 400
    assert resp.json() == {"detail": "Invalid status: not-a-status"}


@pytest.mark.django_db
def test_create_user_short_password_422(superuser, db):
    resp = Client().post(f"{BASE}/admin/users/", data={
        "username": "shorty", "email": "shorty@htq.test", "password": "short",
    }, content_type="application/json", **_auth(superuser))
    assert resp.status_code == 422


@pytest.mark.django_db
def test_create_user_mailbox_requested_without_domain_returns_loud_error(superuser, db):
    """Без настроенного домена корпоративной почты ящик завести невозможно —
    ответ обязан сказать об этом прямо, а не промолчать (поля ``mailbox_*``
    когда-то вообще исчезали из-за ``extra=ignore``). Сам пользователь при
    этом создаётся: отказ почты не должен его откатывать."""
    resp = Client().post(f"{BASE}/admin/users/", data={
        "username": "mailboxer", "email": "mailboxer@htq.test", "password": "Passw0rd!",
        "create_mailbox": True, "mailbox_local_part": "m.boxer",
    }, content_type="application/json", **_auth(superuser))
    assert resp.status_code == 201
    body = resp.json()
    assert "Домен корпоративной почты не настроен" in body["mailbox_error"]
    assert body["mailbox"] is None

    user = User.objects.get(username="mailboxer")
    assert user is not None  # user creation itself still succeeds


@pytest.mark.django_db
def test_create_user_provisions_a_real_mailbox_when_mail_is_configured(superuser, db):
    """Галочка «создать ящик» больше не инертна: ящик действительно
    заводится через apps.mail.interface, а пароль показывается один раз."""
    from apps.mail.models import EmailAccount, ProvisionedMailbox

    with override_settings(
        MAILCOW_DOMAIN="htq.group", MAIL_PROVISIONER="none",
    ):
        resp = Client().post(f"{BASE}/admin/users/", data={
            "username": "boxed", "email": "boxed@htq.test", "password": "Passw0rd!",
            "first_name": "Иван", "last_name": "Иванов",
            "create_mailbox": True,
        }, content_type="application/json", **_auth(superuser))

    assert resp.status_code == 201
    body = resp.json()
    assert body["mailbox_error"] is None
    assert body["mailbox"]["address"] == "i.ivanov@htq.group"
    assert len(body["mailbox"]["generated_password"]) >= 16

    user = User.objects.get(username="boxed")
    assert ProvisionedMailbox.objects.filter(user_id=user.id).exists()
    # И ящик сразу виден пользователю в разделе «Почта».
    assert EmailAccount.objects.filter(user_id=user.id, type="corporate").exists()


@pytest.mark.django_db
def test_create_user_mailbox_conflict_does_not_block_user_creation(superuser, db):
    """Занятый адрес — повод сообщить об этом, но не повод не создать
    сотрудника: ящик админ доведёт руками из раздела «Корпоративные ящики»."""
    from apps.mail.models import ProvisionedMailbox

    ProvisionedMailbox.objects.create(
        local_part="i.ivanov", domain="htq.group", address="i.ivanov@htq.group",
    )
    with override_settings(
        MAILCOW_DOMAIN="htq.group", MAIL_PROVISIONER="imap", IMAP_HOST="mail-tunnel",
    ):
        resp = Client().post(f"{BASE}/admin/users/", data={
            "username": "clash", "email": "clash@htq.test", "password": "Passw0rd!",
            "create_mailbox": True, "mailbox_local_part": "i.ivanov",
            "mailbox_password": "S3cret!",
        }, content_type="application/json", **_auth(superuser))

    assert resp.status_code == 201
    assert "already exists" in resp.json()["mailbox_error"]
    assert User.objects.filter(username="clash").exists()


@pytest.mark.django_db
def test_create_user_no_mailbox_requested_no_error(superuser, db):
    resp = Client().post(f"{BASE}/admin/users/", data={
        "username": "nomailbox", "email": "nomailbox@htq.test", "password": "Passw0rd!",
    }, content_type="application/json", **_auth(superuser))
    assert resp.status_code == 201
    body = resp.json()
    assert body["mailbox_error"] is None
    assert body["mailbox"] is None


# ── PATCH admin/users/{id}/ ──────────────────────────────────────────────────


@pytest.mark.django_db
def test_patch_user_401_without_token(plain_user):
    resp = Client().patch(f"{BASE}/admin/users/{plain_user.id}/", data={"is_staff": True},
                          content_type="application/json")
    assert resp.status_code == 401


@pytest.mark.django_db
def test_patch_user_403_non_admin(plain_user):
    resp = Client().patch(f"{BASE}/admin/users/{plain_user.id}/", data={"is_staff": True},
                          content_type="application/json", **_auth(plain_user))
    assert resp.status_code == 403


@pytest.mark.django_db
def test_patch_user_200_updates_flags(superuser, plain_user):
    resp = Client().patch(f"{BASE}/admin/users/{plain_user.id}/", data={
        "is_staff": True, "status": "suspended",
    }, content_type="application/json", **_auth(superuser))
    assert resp.status_code == 200
    body = resp.json()
    assert body["is_staff"] is True
    assert body["status"] == "suspended"

    plain_user.refresh_from_db()
    assert plain_user.is_staff is True
    assert plain_user.status == UserStatus.SUSPENDED


@pytest.mark.django_db
def test_patch_user_200_partial_unset_fields_untouched(superuser, plain_user):
    """exclude_unset=True — omitted fields must not be clobbered."""
    resp = Client().patch(f"{BASE}/admin/users/{plain_user.id}/", data={
        "phone": "+7 700 000 00 00",
    }, content_type="application/json", **_auth(superuser))
    assert resp.status_code == 200
    plain_user.refresh_from_db()
    assert plain_user.phone == "+7 700 000 00 00"
    assert plain_user.first_name == "Alice"
    assert plain_user.last_name == "Smith"


@pytest.mark.django_db
def test_patch_user_200_settings_as_json_string(superuser, plain_user):
    resp = Client().patch(f"{BASE}/admin/users/{plain_user.id}/", data={
        "settings": "{\"theme\": \"dark\"}",
    }, content_type="application/json", **_auth(superuser))
    assert resp.status_code == 200
    assert resp.json()["settings"] == {"theme": "dark"}
    plain_user.refresh_from_db()
    assert plain_user.settings == {"theme": "dark"}


@pytest.mark.django_db
def test_patch_user_400_invalid_settings_json(superuser, plain_user):
    resp = Client().patch(f"{BASE}/admin/users/{plain_user.id}/", data={
        "settings": "not-json",
    }, content_type="application/json", **_auth(superuser))
    assert resp.status_code == 400


@pytest.mark.django_db
def test_patch_user_400_invalid_status_and_nothing_persisted(superuser, plain_user):
    """Review finding: a bare ``setattr`` + ``.save()`` doesn't enforce Django
    ``choices`` — an invalid ``status`` string must be rejected the same way
    ``create_user`` rejects it (same error shape), and the DB row must be
    left untouched (proving nothing was persisted), not silently corrupted."""
    original_status = plain_user.status
    resp = Client().patch(f"{BASE}/admin/users/{plain_user.id}/", data={
        "status": "garbage",
    }, content_type="application/json", **_auth(superuser))
    assert resp.status_code == 400
    assert resp.json() == {"detail": "Invalid status: garbage"}

    plain_user.refresh_from_db()
    assert plain_user.status == original_status


@pytest.mark.django_db
def test_patch_user_400_duplicate_email(superuser, plain_user, staff_user):
    resp = Client().patch(f"{BASE}/admin/users/{plain_user.id}/", data={
        "email": "staffer@htq.test",
    }, content_type="application/json", **_auth(superuser))
    assert resp.status_code == 400
    assert resp.json() == {"detail": "Email already in use"}


@pytest.mark.django_db
def test_patch_user_400_duplicate_username(superuser, plain_user, staff_user):
    resp = Client().patch(f"{BASE}/admin/users/{plain_user.id}/", data={
        "username": "staffer",
    }, content_type="application/json", **_auth(superuser))
    assert resp.status_code == 400
    assert resp.json() == {"detail": "Username already in use"}


@pytest.mark.django_db
def test_patch_user_404_unknown_id(superuser, db):
    resp = Client().patch(f"{BASE}/admin/users/999999/", data={"is_staff": True},
                          content_type="application/json", **_auth(superuser))
    assert resp.status_code == 404
    assert resp.json() == {"detail": "User not found"}


# ── POST admin/users/{id}/set-password/ ──────────────────────────────────────


@pytest.mark.django_db
def test_set_password_401_without_token(plain_user):
    resp = Client().post(f"{BASE}/admin/users/{plain_user.id}/set-password/", data={
        "new_password": "NewPassw0rd!",
    }, content_type="application/json")
    assert resp.status_code == 401


@pytest.mark.django_db
def test_set_password_403_non_admin(plain_user):
    resp = Client().post(f"{BASE}/admin/users/{plain_user.id}/set-password/", data={
        "new_password": "NewPassw0rd!",
    }, content_type="application/json", **_auth(plain_user))
    assert resp.status_code == 403


@pytest.mark.django_db
def test_set_password_200_changes_password_and_flags_must_change(superuser, plain_user):
    resp = Client().post(f"{BASE}/admin/users/{plain_user.id}/set-password/", data={
        "new_password": "NewPassw0rd!",
    }, content_type="application/json", **_auth(superuser))
    assert resp.status_code == 200
    assert resp.json() == {"detail": "Password updated"}

    plain_user.refresh_from_db()
    assert plain_user.check_password("NewPassw0rd!") is True
    assert plain_user.check_password("S3cret!") is False
    assert plain_user.must_change_password is True  # default


@pytest.mark.django_db
def test_set_password_200_must_change_password_false(superuser, plain_user):
    resp = Client().post(f"{BASE}/admin/users/{plain_user.id}/set-password/", data={
        "new_password": "NewPassw0rd!", "must_change_password": False,
    }, content_type="application/json", **_auth(superuser))
    assert resp.status_code == 200
    plain_user.refresh_from_db()
    assert plain_user.must_change_password is False


@pytest.mark.django_db
def test_set_password_404_unknown_id(superuser, db):
    resp = Client().post(f"{BASE}/admin/users/999999/set-password/", data={
        "new_password": "NewPassw0rd!",
    }, content_type="application/json", **_auth(superuser))
    assert resp.status_code == 404
    assert resp.json() == {"detail": "User not found"}


@pytest.mark.django_db
def test_set_password_422_too_short(superuser, plain_user):
    resp = Client().post(f"{BASE}/admin/users/{plain_user.id}/set-password/", data={
        "new_password": "short",
    }, content_type="application/json", **_auth(superuser))
    assert resp.status_code == 422


# ── DELETE admin/users/{id}/ ─────────────────────────────────────────────────


@pytest.mark.django_db
def test_delete_user_401_without_token(plain_user):
    resp = Client().delete(f"{BASE}/admin/users/{plain_user.id}/")
    assert resp.status_code == 401


@pytest.mark.django_db
def test_delete_user_403_non_admin(plain_user, staff_user):
    resp = Client().delete(f"{BASE}/admin/users/{staff_user.id}/", **_auth(plain_user))
    assert resp.status_code == 403


@pytest.mark.django_db
def test_delete_user_204_soft_deletes_status_suspended(superuser, plain_user):
    resp = Client().delete(f"{BASE}/admin/users/{plain_user.id}/", **_auth(superuser))
    assert resp.status_code == 204
    assert resp.content == b""

    plain_user.refresh_from_db()
    assert plain_user.status == UserStatus.SUSPENDED
    assert plain_user.is_staff is False
    assert plain_user.is_superuser is False


@pytest.mark.django_db
def test_delete_user_soft_deleted_cannot_authenticate(superuser, plain_user):
    resp = Client().delete(f"{BASE}/admin/users/{plain_user.id}/", **_auth(superuser))
    assert resp.status_code == 204

    login = Client().post(f"{BASE}/token/", data={
        "email": "alice@htq.test", "password": "S3cret!",
    }, content_type="application/json")
    assert login.status_code == 401
    assert login.json() == {"detail": "Account is not activated"}


@pytest.mark.django_db
def test_delete_user_strips_elevated_flags(superuser, staff_user):
    resp = Client().delete(f"{BASE}/admin/users/{staff_user.id}/", **_auth(superuser))
    assert resp.status_code == 204
    staff_user.refresh_from_db()
    assert staff_user.is_staff is False
    assert staff_user.status == UserStatus.SUSPENDED


@pytest.mark.django_db
def test_delete_user_400_cannot_delete_self(superuser):
    resp = Client().delete(f"{BASE}/admin/users/{superuser.id}/", **_auth(superuser))
    assert resp.status_code == 400
    assert resp.json() == {"detail": "Cannot delete yourself"}
    superuser.refresh_from_db()
    assert superuser.status == UserStatus.ACTIVE


@pytest.mark.django_db
def test_delete_user_404_unknown_id(superuser, db):
    resp = Client().delete(f"{BASE}/admin/users/999999/", **_auth(superuser))
    assert resp.status_code == 404
    assert resp.json() == {"detail": "User not found"}


# ── GET admin/users/{id}/ — not registered (source has no single-user GET) ──


@pytest.mark.django_db
def test_get_single_user_405_not_a_route(superuser, plain_user):
    resp = Client().get(f"{BASE}/admin/users/{plain_user.id}/", **_auth(superuser))
    assert resp.status_code == 405
