"""Контракт /api/email/v1/accounts/* — паритет с
services/email/app/api/v1/accounts.py (4 эндпойнта):

  GET    /accounts/                        — list_accounts
  POST   /accounts/{id}/set-default/       — set_default_account
  POST   /accounts/{id}/sync/               — trigger_account_sync (202)
  DELETE /accounts/{id}/                    — disconnect_account (204)

Авторизация (решение 3 брифа): обычный JWT-пользователь
(``get_current_user`` исходника) → ``auth="jwt"``. Аккаунт привязан к
``user_id`` из токена — пользователь видит/правит ТОЛЬКО свои строки; чужой
id -> 404 "Account not found" (буквально как в исходнике, не 403 — сокрытие
существования).

Р2 (брифа): dramatiq-события (``incremental_sync_account.send(...)``) НЕ
портируются — sync-эндпойнт просто резолвит/валидирует аккаунт и возвращает
202 без фактической постановки в очередь (под-задача workers).
"""
import datetime

import pytest
from django.test import Client

from apps.mail.models import AccountProvider, AccountType, EmailAccount, OAuthToken
from apps.mail.services import account_service, oauth_clients
from apps.users.models import User, UserStatus
from htqweb.authn.jwt import issue_token_pair

BASE = "/api/email/v1/accounts"


@pytest.fixture
def user(db):
    u = User.objects.create(
        username="mail-user", email="mail@htq.test", password="x", status=UserStatus.ACTIVE,
    )
    u.set_password("S3cret!")
    u.save()
    return u


@pytest.fixture
def other_user(db):
    u = User.objects.create(
        username="other-user", email="other@htq.test", password="x", status=UserStatus.ACTIVE,
    )
    u.set_password("S3cret!")
    u.save()
    return u


@pytest.fixture
def auth(user):
    return {"HTTP_AUTHORIZATION": f"Bearer {issue_token_pair(user)['access']}"}


@pytest.fixture
def other_auth(other_user):
    return {"HTTP_AUTHORIZATION": f"Bearer {issue_token_pair(other_user)['access']}"}


def _token(user_id, **kw):
    defaults = dict(
        user_id=user_id, provider="google", provider_account_id="acct@example.com",
        encrypted_access_token="enc-access", expires_at=datetime.datetime.now(datetime.timezone.utc),
    )
    defaults.update(kw)
    return OAuthToken.objects.create(**defaults)


def _personal_account(user_id, address, **kw):
    tok = _token(user_id, provider_account_id=address)
    defaults = dict(
        user_id=user_id, type=AccountType.PERSONAL, provider=AccountProvider.GOOGLE,
        address=address, oauth_token=tok,
    )
    defaults.update(kw)
    return EmailAccount.objects.create(**defaults)


def _corporate_account(user_id, address, mailbox_id, **kw):
    defaults = dict(
        user_id=user_id, type=AccountType.CORPORATE, provider=AccountProvider.MAILCOW,
        address=address, mailbox_id=mailbox_id,
    )
    defaults.update(kw)
    return EmailAccount.objects.create(**defaults)


# ── auth ─────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_requires_jwt():
    assert Client().get(f"{BASE}/").status_code == 401


# ── GET /accounts/ ───────────────────────────────────────────────────────

@pytest.mark.django_db
def test_list_returns_only_own_accounts_ordered_default_first(user, other_user, auth):
    _personal_account(user.id, "second@example.com")
    default_acc = _personal_account(user.id, "first@example.com", is_default=True)
    _personal_account(other_user.id, "not-mine@example.com")

    resp = Client().get(f"{BASE}/", **auth)
    assert resp.status_code == 200
    body = resp.json()
    assert [a["id"] for a in body] == [default_acc.id] + [
        a.id for a in EmailAccount.objects.filter(user_id=user.id).exclude(id=default_acc.id).order_by("id")
    ]
    assert {"id", "type", "provider", "address", "display_name", "is_default",
            "is_active", "last_sync_at", "last_sync_error", "watch_expires_at",
            "connected_at", "unread_count"} == set(body[0])
    assert body[0]["unread_count"] == 0


@pytest.mark.django_db
def test_list_unread_count_is_real_inbox_unread_count_per_account(user, auth):
    """mail-messages-brief.md п.7 — растяжка снята: unread_count теперь
    считает EmailMessage(account=, folder='inbox', is_read=False),
    буквально как исходник (accounts.py::list_accounts, коррелированный
    подзапрос)."""
    import datetime

    from apps.mail.models import EmailMessage

    acc = _personal_account(user.id, "unread@example.com")
    other_acc = _personal_account(user.id, "other@example.com")
    now = datetime.datetime.now(datetime.timezone.utc)

    EmailMessage.objects.create(
        user_id=user.id, account=acc, folder="inbox", is_read=False,
        sender_email="a@example.com", date=now,
    )
    EmailMessage.objects.create(
        user_id=user.id, account=acc, folder="inbox", is_read=False,
        sender_email="b@example.com", date=now,
    )
    # Read inbox message — must NOT count.
    EmailMessage.objects.create(
        user_id=user.id, account=acc, folder="inbox", is_read=True,
        sender_email="c@example.com", date=now,
    )
    # Unread but not inbox — must NOT count.
    EmailMessage.objects.create(
        user_id=user.id, account=acc, folder="sent", is_read=False,
        sender_email="d@example.com", date=now,
    )
    # Different account — must not bleed into acc's count.
    EmailMessage.objects.create(
        user_id=user.id, account=other_acc, folder="inbox", is_read=False,
        sender_email="e@example.com", date=now,
    )

    resp = Client().get(f"{BASE}/", **auth)
    assert resp.status_code == 200
    by_id = {row["id"]: row["unread_count"] for row in resp.json()}
    assert by_id[acc.id] == 2
    assert by_id[other_acc.id] == 1


@pytest.mark.django_db
def test_list_empty_when_no_accounts(auth):
    resp = Client().get(f"{BASE}/", **auth)
    assert resp.status_code == 200
    assert resp.json() == []


# ── POST /accounts/{id}/set-default/ ────────────────────────────────────

@pytest.mark.django_db
def test_set_default_swaps_atomically(user, auth):
    a = _personal_account(user.id, "a@example.com", is_default=True)
    b = _personal_account(user.id, "b@example.com")

    resp = Client().post(f"{BASE}/{b.id}/set-default/", **auth)
    assert resp.status_code == 200
    assert resp.json()["is_default"] is True

    a.refresh_from_db()
    b.refresh_from_db()
    assert a.is_default is False
    assert b.is_default is True


@pytest.mark.django_db
def test_set_default_404_when_not_found(auth):
    resp = Client().post(f"{BASE}/999999/set-default/", **auth)
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Account not found"


@pytest.mark.django_db
def test_set_default_404_when_not_owned(other_user, auth):
    acc = _personal_account(other_user.id, "notmine@example.com")
    resp = Client().post(f"{BASE}/{acc.id}/set-default/", **auth)
    assert resp.status_code == 404


# ── POST /accounts/{id}/sync/ ────────────────────────────────────────────

@pytest.mark.django_db
def test_sync_returns_202_with_shape(user, auth):
    acc = _personal_account(user.id, "sync@example.com")
    resp = Client().post(f"{BASE}/{acc.id}/sync/", **auth)
    assert resp.status_code == 202
    body = resp.json()
    assert body["account_id"] == acc.id
    assert body["status"] == "queued"
    assert "queued_at" in body


@pytest.mark.django_db
def test_sync_404_when_not_owned(other_user, auth):
    acc = _personal_account(other_user.id, "notmine2@example.com")
    resp = Client().post(f"{BASE}/{acc.id}/sync/", **auth)
    assert resp.status_code == 404


@pytest.mark.django_db
def test_sync_409_when_inactive(user, auth):
    acc = _personal_account(user.id, "inactive@example.com", is_active=False)
    resp = Client().post(f"{BASE}/{acc.id}/sync/", **auth)
    assert resp.status_code == 409
    assert resp.json()["detail"] == "Account is inactive"


# ── DELETE /accounts/{id}/ ───────────────────────────────────────────────

@pytest.mark.django_db
def test_disconnect_404_when_not_found(auth):
    resp = Client().delete(f"{BASE}/999999/", **auth)
    assert resp.status_code == 404


@pytest.mark.django_db
def test_disconnect_404_when_not_owned(other_user, auth):
    acc = _personal_account(other_user.id, "notmine3@example.com")
    resp = Client().delete(f"{BASE}/{acc.id}/", **auth)
    assert resp.status_code == 404


@pytest.mark.django_db
def test_disconnect_400_for_corporate_account(user, auth):
    acc = _corporate_account(user.id, "corp@example.com", mailbox_id=101)
    resp = Client().delete(f"{BASE}/{acc.id}/", **auth)
    assert resp.status_code == 400
    assert "mailboxes/" in resp.json()["detail"]
    assert EmailAccount.objects.filter(id=acc.id).exists()


@pytest.mark.django_db
def test_disconnect_personal_deletes_account_and_token_best_effort_revoke(user, auth, monkeypatch):
    tok = _token(user.id)
    acc = EmailAccount.objects.create(
        user_id=user.id, type=AccountType.PERSONAL, provider=AccountProvider.GOOGLE,
        address="revoke-me@example.com", oauth_token=tok,
    )

    revoked = {}

    class FakeClient:
        def revoke(self, access_token):
            revoked["access_token"] = access_token

    monkeypatch.setattr(account_service, "get_oauth_client", lambda provider: FakeClient())
    monkeypatch.setattr(
        account_service.crypto_service, "decrypt", lambda enc: "plain-access-token",
    )

    resp = Client().delete(f"{BASE}/{acc.id}/", **auth)
    assert resp.status_code == 204
    assert not EmailAccount.objects.filter(id=acc.id).exists()
    assert not OAuthToken.objects.filter(id=tok.id).exists()
    assert revoked["access_token"] == "plain-access-token"


@pytest.mark.django_db
def test_disconnect_personal_survives_revoke_failure(user, auth, monkeypatch):
    """Best-effort: revoke падает -> аккаунт всё равно удаляется (буквальный
    порт accounts.py::disconnect_account — исходник глотает Exception и
    только логирует warning)."""
    tok = _token(user.id)
    acc = EmailAccount.objects.create(
        user_id=user.id, type=AccountType.PERSONAL, provider=AccountProvider.GOOGLE,
        address="revoke-fails@example.com", oauth_token=tok,
    )

    def _boom(provider):
        raise RuntimeError("provider unreachable")

    monkeypatch.setattr(account_service, "get_oauth_client", _boom)

    resp = Client().delete(f"{BASE}/{acc.id}/", **auth)
    assert resp.status_code == 204
    assert not EmailAccount.objects.filter(id=acc.id).exists()
