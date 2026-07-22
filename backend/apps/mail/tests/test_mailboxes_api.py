"""Контракт /api/email/v1/mailboxes/* — паритет с
services/email/app/api/v1/mailboxes.py (mailboxes-под-задача,
mail-mailboxes-brief.md, 12 эндпойнтов):

  GET    /mailboxes/                     — list_mailboxes
  POST   /mailboxes/                     — create_mailbox
  GET    /mailboxes/{id}/                — get_mailbox
  PATCH  /mailboxes/{id}/                — update_mailbox
  POST   /mailboxes/{id}/reset-password/ — reset_mailbox_password
  POST   /mailboxes/{id}/archive/        — archive_mailbox
  POST   /mailboxes/{id}/restore/        — restore_mailbox
  DELETE /mailboxes/{id}/                — delete_mailbox (stage 2)
  GET    /mailboxes/aliases/             — list_aliases (проксируется в Mailcow)
  POST   /mailboxes/aliases/             — create_alias
  DELETE /mailboxes/aliases/{alias_id}/  — delete_alias
  POST   /mailboxes/{id}/forwarding/     — set_forwarding

Авторизация (``require_mailbox_admin`` исходника — см. apps/mail/views.py
докстринг): user-JWT с is_staff/is_superuser/is_admin. S2S-ветка исходника
не переносится (PLAN.md Р3, "без S2S") -> ``api_view(auth="jwt",
admin=True)``, тот же ``is_elevated``-предикат, что и apps/hr positions/org.

Живая сеть в Mailcow нигде не участвует: aliases/forwarding монkeypatch'ят
``apps.mail.views.MailcowClient`` (тот же модуль, что инстанцирует его
напрямую — буквально как исходный роутер), CRUD-эндпойнты вообще не трогают
MailcowClient (Р2 — постановка в очередь Dramatiq-актора НЕ портируется,
см. apps/mail/services/mailbox_service.py докстринг)."""
from __future__ import annotations

import pytest
from django.test import Client, override_settings

from apps.mail.models import MailboxStatus, ProvisionedMailbox
from apps.users.models import User, UserStatus
from htqweb.authn.jwt import issue_token_pair

BASE = "/api/email/v1/mailboxes"


@pytest.fixture
def user(db):
    u = User.objects.create(username="mbx-user", email="mbx-user@htq.test", password="x", status=UserStatus.ACTIVE)
    u.set_password("S3cret!")
    u.save()
    return u


@pytest.fixture
def admin_user(db):
    u = User.objects.create(
        username="mbx-admin", email="mbx-admin@htq.test", password="x", status=UserStatus.ACTIVE, is_staff=True,
    )
    u.set_password("Adm1n!Pass")
    u.save()
    return u


@pytest.fixture
def auth(user):
    return {"HTTP_AUTHORIZATION": f"Bearer {issue_token_pair(user)['access']}"}


@pytest.fixture
def admin_auth(admin_user):
    return {"HTTP_AUTHORIZATION": f"Bearer {issue_token_pair(admin_user)['access']}"}


def _mailbox(**kw) -> ProvisionedMailbox:
    defaults = dict(local_part="ivan", domain="htq.group", address="ivan@htq.group")
    defaults.update(kw)
    return ProvisionedMailbox.objects.create(**defaults)


# ── auth ─────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_requires_jwt():
    assert Client().get(f"{BASE}/").status_code == 401


@pytest.mark.django_db
def test_requires_elevated_jwt_forbidden_for_plain_user(auth):
    resp = Client().get(f"{BASE}/", **auth)
    assert resp.status_code == 403


@pytest.mark.django_db
@pytest.mark.parametrize("method,path", [
    ("get", ""), ("post", ""),
    ("get", "/1/"), ("patch", "/1/"), ("delete", "/1/"),
    ("post", "/1/reset-password/"), ("post", "/1/archive/"), ("post", "/1/restore/"),
    ("get", "/aliases/"), ("post", "/aliases/"), ("delete", "/aliases/1/"),
    ("post", "/1/forwarding/"),
])
def test_all_12_routes_require_admin(auth, method, path):
    """Каждый из 12 эндпойнтов проходит через один и тот же admin-гейт —
    неэлевированный JWT получает 403 на всех, независимо от метода/тела."""
    resp = getattr(Client(), method)(f"{BASE}{path}/".replace("//", "/"), **auth)
    assert resp.status_code == 403


# ── GET /mailboxes/ ──────────────────────────────────────────────────────

@pytest.mark.django_db
def test_list_excludes_deleted_by_default(admin_auth):
    active = _mailbox(address="active@htq.group", status=MailboxStatus.ACTIVE)
    _mailbox(address="deleted@htq.group", status=MailboxStatus.DELETED)

    resp = Client().get(f"{BASE}/", **admin_auth)
    assert resp.status_code == 200
    body = resp.json()
    assert [m["id"] for m in body] == [active.id]


@pytest.mark.django_db
def test_list_include_deleted_true_returns_all(admin_auth):
    active = _mailbox(address="active2@htq.group", status=MailboxStatus.ACTIVE)
    deleted = _mailbox(address="deleted2@htq.group", status=MailboxStatus.DELETED)

    resp = Client().get(f"{BASE}/?include_deleted=true", **admin_auth)
    assert resp.status_code == 200
    ids = {m["id"] for m in resp.json()}
    assert ids == {active.id, deleted.id}


@pytest.mark.django_db
def test_list_ordered_newest_first(admin_auth):
    first = _mailbox(address="a@htq.group")
    second = _mailbox(address="b@htq.group")
    resp = Client().get(f"{BASE}/", **admin_auth)
    assert [m["id"] for m in resp.json()] == [second.id, first.id]


@pytest.mark.django_db
def test_list_invalid_include_deleted_is_422(admin_auth):
    resp = Client().get(f"{BASE}/?include_deleted=maybe", **admin_auth)
    assert resp.status_code == 422


@pytest.mark.django_db
def test_list_row_shape(admin_auth):
    _mailbox()
    resp = Client().get(f"{BASE}/", **admin_auth)
    row = resp.json()[0]
    assert set(row) == {
        "id", "user_id", "local_part", "domain", "address", "status", "quota_mb",
        "display_name", "last_error", "created_at", "updated_at", "archived_at", "deleted_at",
    }


# ── POST /mailboxes/ ──────────────────────────────────────────────────────

@pytest.mark.django_db
def test_create_requires_mailcow_domain_configured(admin_auth):
    resp = Client().post(f"{BASE}/", data=b"{}", content_type="application/json", **admin_auth)
    assert resp.status_code == 500
    assert resp.json()["detail"] == "MAILCOW_DOMAIN not configured"


@pytest.mark.django_db
def test_create_with_explicit_local_part_and_password(admin_auth):
    with override_settings(MAILCOW_DOMAIN="htq.group"):
        resp = Client().post(
            f"{BASE}/",
            data={"local_part": "j.doe", "password": "MyStr0ngPass!", "quota_mb": 2048},
            content_type="application/json", **admin_auth,
        )
    assert resp.status_code == 201
    body = resp.json()
    assert body["address"] == "j.doe@htq.group"
    assert body["status"] == "active"
    assert body["quota_mb"] == 2048
    assert body["generated_password"] is None  # admin supplied one, never echoed


@pytest.mark.django_db
def test_create_autogenerates_local_part_from_name_and_password(admin_auth):
    with override_settings(MAILCOW_DOMAIN="htq.group"):
        resp = Client().post(
            f"{BASE}/",
            data={"first_name": "Иван", "last_name": "Иванов"},
            content_type="application/json", **admin_auth,
        )
    assert resp.status_code == 201
    body = resp.json()
    assert body["address"] == "i.ivanov@htq.group"
    assert body["quota_mb"] == 1024
    assert isinstance(body["generated_password"], str) and len(body["generated_password"]) >= 16


@pytest.mark.django_db
def test_create_deduplicates_local_part_on_conflict(admin_auth):
    _mailbox(local_part="i.ivanov", domain="htq.group", address="i.ivanov@htq.group")
    with override_settings(MAILCOW_DOMAIN="htq.group"):
        resp = Client().post(
            f"{BASE}/",
            data={"local_part": "i.ivanov"},
            content_type="application/json", **admin_auth,
        )
    assert resp.status_code == 201
    assert resp.json()["address"] == "i.ivanov2@htq.group"


@pytest.mark.django_db
def test_create_rejects_invalid_local_part(admin_auth):
    with override_settings(MAILCOW_DOMAIN="htq.group"):
        resp = Client().post(
            f"{BASE}/",
            data={"local_part": "!!!"},
            content_type="application/json", **admin_auth,
        )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Invalid local_part"


@pytest.mark.django_db
def test_create_conflicts_when_user_already_has_mailbox(admin_auth):
    existing = _mailbox(user_id=42, address="existing@htq.group")
    with override_settings(MAILCOW_DOMAIN="htq.group"):
        resp = Client().post(
            f"{BASE}/",
            data={"local_part": "second", "user_id": 42},
            content_type="application/json", **admin_auth,
        )
    assert resp.status_code == 409
    assert resp.json()["detail"] == f"User 42 already has mailbox {existing.address}"


@pytest.mark.django_db
def test_create_after_previous_deletion_hits_latent_unique_user_id_bug(admin_auth):
    """Задокументированная странность исходника (тот же класс "живой баг",
    что и disconnect_account в account_service.py): ``create()`` НАМЕРЕННО
    пропускает conflict-проверку, когда старая строка ``status='deleted'``
    (``if existing and existing.status != "deleted": raise 409``) — код
    предполагает, что для пользователя можно завести НОВЫЙ ящик после
    удаления старого. Но ``ProvisionedMailbox.user_id`` несёт БЕЗУСЛОВНЫЙ
    ``UniqueConstraint("user_id", ...)`` (mailbox.py исходника, без WHERE —
    не partial), который блокирует ЛЮБУЮ новую строку с тем же user_id,
    включая эту "разрешённую" ветку. Источник никогда не ловит этот
    IntegrityError здесь -> необработанные 500 и там, и в этом порту.
    Перенесено буквально, не "исправлено"."""
    _mailbox(user_id=42, address="old@htq.group", status=MailboxStatus.DELETED)
    with override_settings(MAILCOW_DOMAIN="htq.group"):
        resp = Client().post(
            f"{BASE}/",
            data={"local_part": "new", "user_id": 42},
            content_type="application/json", **admin_auth,
        )
    assert resp.status_code == 500


# ── GET /mailboxes/{id}/ ──────────────────────────────────────────────────

@pytest.mark.django_db
def test_get_returns_row(admin_auth):
    mb = _mailbox()
    resp = Client().get(f"{BASE}/{mb.id}/", **admin_auth)
    assert resp.status_code == 200
    assert resp.json()["id"] == mb.id


@pytest.mark.django_db
def test_get_404_when_not_found(admin_auth):
    resp = Client().get(f"{BASE}/999999/", **admin_auth)
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Mailbox not found"


# ── PATCH /mailboxes/{id}/ ────────────────────────────────────────────────

@pytest.mark.django_db
def test_update_full_name_and_quota(admin_auth):
    mb = _mailbox()
    resp = Client().patch(
        f"{BASE}/{mb.id}/", data={"full_name": "New Name", "quota_mb": 4096},
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["display_name"] == "New Name"
    assert body["quota_mb"] == 4096


@pytest.mark.django_db
def test_update_404_when_not_found(admin_auth):
    resp = Client().patch(
        f"{BASE}/999999/", data={"full_name": "x"}, content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 404


@pytest.mark.django_db
def test_update_409_when_already_deleted(admin_auth):
    mb = _mailbox(status=MailboxStatus.DELETED)
    resp = Client().patch(
        f"{BASE}/{mb.id}/", data={"full_name": "x"}, content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 409
    assert resp.json()["detail"] == "Mailbox already deleted"


# ── POST /mailboxes/{id}/reset-password/ ──────────────────────────────────

@pytest.mark.django_db
def test_reset_password_active_mailbox_autogenerates(admin_auth):
    mb = _mailbox(status=MailboxStatus.ACTIVE)
    resp = Client().post(
        f"{BASE}/{mb.id}/reset-password/", data=b"{}", content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body["generated_password"], str) and len(body["generated_password"]) >= 16


@pytest.mark.django_db
def test_reset_password_explicit_password_not_echoed(admin_auth):
    mb = _mailbox(status=MailboxStatus.ACTIVE)
    resp = Client().post(
        f"{BASE}/{mb.id}/reset-password/", data={"new_password": "Expl1cit!"},
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 200
    assert resp.json()["generated_password"] is None


@pytest.mark.django_db
def test_reset_password_409_when_not_active(admin_auth):
    mb = _mailbox(status=MailboxStatus.ARCHIVED)
    resp = Client().post(
        f"{BASE}/{mb.id}/reset-password/", data=b"{}", content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 409
    assert resp.json()["detail"] == "Mailbox is not active"


@pytest.mark.django_db
def test_reset_password_404_when_not_found(admin_auth):
    resp = Client().post(
        f"{BASE}/999999/reset-password/", data=b"{}", content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 404


# ── POST /mailboxes/{id}/archive/ ─────────────────────────────────────────

@pytest.mark.django_db
def test_archive_active_mailbox(admin_auth):
    mb = _mailbox(status=MailboxStatus.ACTIVE)
    resp = Client().post(f"{BASE}/{mb.id}/archive/", **admin_auth)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "archived"
    assert body["archived_at"] is not None


@pytest.mark.django_db
def test_archive_error_mailbox_also_allowed(admin_auth):
    mb = _mailbox(status=MailboxStatus.ERROR)
    resp = Client().post(f"{BASE}/{mb.id}/archive/", **admin_auth)
    assert resp.status_code == 200
    assert resp.json()["status"] == "archived"


@pytest.mark.django_db
def test_archive_is_idempotent_when_already_archived(admin_auth):
    mb = _mailbox(status=MailboxStatus.ARCHIVED)
    resp = Client().post(f"{BASE}/{mb.id}/archive/", **admin_auth)
    assert resp.status_code == 200
    assert resp.json()["status"] == "archived"


@pytest.mark.django_db
def test_archive_409_when_deleted(admin_auth):
    mb = _mailbox(status=MailboxStatus.DELETED)
    resp = Client().post(f"{BASE}/{mb.id}/archive/", **admin_auth)
    assert resp.status_code == 409
    assert resp.json()["detail"] == "Cannot archive mailbox in status=deleted"


@pytest.mark.django_db
def test_archive_404_when_not_found(admin_auth):
    resp = Client().post(f"{BASE}/999999/archive/", **admin_auth)
    assert resp.status_code == 404


# ── POST /mailboxes/{id}/restore/ ─────────────────────────────────────────

@pytest.mark.django_db
def test_restore_archived_mailbox(admin_auth):
    mb = _mailbox(status=MailboxStatus.ARCHIVED)
    resp = Client().post(f"{BASE}/{mb.id}/restore/", **admin_auth)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "active"
    assert body["archived_at"] is None


@pytest.mark.django_db
def test_restore_409_when_not_archived(admin_auth):
    mb = _mailbox(status=MailboxStatus.ACTIVE)
    resp = Client().post(f"{BASE}/{mb.id}/restore/", **admin_auth)
    assert resp.status_code == 409
    assert resp.json()["detail"] == "Only archived mailboxes can be restored"


@pytest.mark.django_db
def test_restore_404_when_not_found(admin_auth):
    resp = Client().post(f"{BASE}/999999/restore/", **admin_auth)
    assert resp.status_code == 404


# ── DELETE /mailboxes/{id}/ (stage 2) ─────────────────────────────────────

@pytest.mark.django_db
def test_delete_archived_mailbox(admin_auth):
    mb = _mailbox(status=MailboxStatus.ARCHIVED)
    resp = Client().delete(f"{BASE}/{mb.id}/", **admin_auth)
    assert resp.status_code == 204
    mb.refresh_from_db()
    assert mb.status == "deleted"
    assert mb.deleted_at is not None


@pytest.mark.django_db
def test_delete_409_when_not_archived(admin_auth):
    mb = _mailbox(status=MailboxStatus.ACTIVE)
    resp = Client().delete(f"{BASE}/{mb.id}/", **admin_auth)
    assert resp.status_code == 409
    assert resp.json()["detail"] == "Mailbox must be archived before permanent deletion"


@pytest.mark.django_db
def test_delete_404_when_not_found(admin_auth):
    resp = Client().delete(f"{BASE}/999999/", **admin_auth)
    assert resp.status_code == 404


# ── /mailboxes/aliases/* (проксируется живьём в Mailcow) ──────────────────

class _FakeMailcowClient:
    calls: list = []

    def __init__(self, *a, **kw):
        pass

    def list_aliases(self):
        _FakeMailcowClient.calls.append(("list_aliases",))
        return [{"id": 1, "address": "sales@htq.group", "goto": "a@htq.group", "active": 1}]

    def add_alias(self, *, address, goto, active):
        _FakeMailcowClient.calls.append(("add_alias", address, goto, active))
        return {"type": "success", "msg": "alias_added"}

    def delete_alias(self, alias_id):
        _FakeMailcowClient.calls.append(("delete_alias", alias_id))
        return [{"type": "success", "msg": "alias_removed"}]

    def set_forwarding(self, address, forward_to, *, keep_local_copy):
        _FakeMailcowClient.calls.append(("set_forwarding", address, forward_to, keep_local_copy))
        return {"type": "success", "msg": "forwarding_set"}


class _RaisingMailcowClient:
    def __init__(self, *a, **kw):
        pass

    def list_aliases(self):
        raise RuntimeError("mailcow unreachable")

    def add_alias(self, **kw):
        raise RuntimeError("mailcow unreachable")

    def delete_alias(self, alias_id):
        raise RuntimeError("mailcow unreachable")

    def set_forwarding(self, *a, **kw):
        raise RuntimeError("mailcow unreachable")


@pytest.fixture(autouse=True)
def _reset_fake_calls():
    _FakeMailcowClient.calls = []
    yield


@pytest.mark.django_db
def test_list_aliases_proxies_to_mailcow(admin_auth, monkeypatch):
    import apps.mail.views as views_mod
    monkeypatch.setattr(views_mod, "MailcowClient", _FakeMailcowClient)

    resp = Client().get(f"{BASE}/aliases/", **admin_auth)
    assert resp.status_code == 200
    assert resp.json() == [{"id": 1, "address": "sales@htq.group", "goto": "a@htq.group", "active": 1}]
    assert ("list_aliases",) in _FakeMailcowClient.calls


@pytest.mark.django_db
def test_list_aliases_mailcow_error_is_502(admin_auth, monkeypatch):
    import apps.mail.views as views_mod
    monkeypatch.setattr(views_mod, "MailcowClient", _RaisingMailcowClient)

    resp = Client().get(f"{BASE}/aliases/", **admin_auth)
    assert resp.status_code == 502
    assert resp.json()["detail"] == "Mailcow error: mailcow unreachable"


@pytest.mark.django_db
def test_create_alias_proxies_to_mailcow(admin_auth, monkeypatch):
    import apps.mail.views as views_mod
    monkeypatch.setattr(views_mod, "MailcowClient", _FakeMailcowClient)

    resp = Client().post(
        f"{BASE}/aliases/", data={"address": "sales@htq.group", "goto": "a@htq.group,b@htq.group"},
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 201
    assert ("add_alias", "sales@htq.group", "a@htq.group,b@htq.group", True) in _FakeMailcowClient.calls


@pytest.mark.django_db
def test_create_alias_invalid_address_is_422(admin_auth):
    resp = Client().post(
        f"{BASE}/aliases/", data={"address": "not-an-email", "goto": "a@htq.group"},
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 422


@pytest.mark.django_db
def test_delete_alias_proxies_to_mailcow(admin_auth, monkeypatch):
    import apps.mail.views as views_mod
    monkeypatch.setattr(views_mod, "MailcowClient", _FakeMailcowClient)

    resp = Client().delete(f"{BASE}/aliases/42/", **admin_auth)
    assert resp.status_code == 204
    assert ("delete_alias", 42) in _FakeMailcowClient.calls


@pytest.mark.django_db
def test_delete_alias_mailcow_error_is_502(admin_auth, monkeypatch):
    import apps.mail.views as views_mod
    monkeypatch.setattr(views_mod, "MailcowClient", _RaisingMailcowClient)

    resp = Client().delete(f"{BASE}/aliases/42/", **admin_auth)
    assert resp.status_code == 502


# ── POST /mailboxes/{id}/forwarding/ ──────────────────────────────────────

@pytest.mark.django_db
def test_set_forwarding_proxies_to_mailcow(admin_auth, monkeypatch):
    import apps.mail.views as views_mod
    monkeypatch.setattr(views_mod, "MailcowClient", _FakeMailcowClient)

    mb = _mailbox(address="ivan@htq.group")
    resp = Client().post(
        f"{BASE}/{mb.id}/forwarding/", data={"forward_to": "ext@example.com"},
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 201
    assert ("set_forwarding", "ivan@htq.group", "ext@example.com", True) in _FakeMailcowClient.calls


@pytest.mark.django_db
def test_set_forwarding_404_when_mailbox_not_found(admin_auth):
    resp = Client().post(
        f"{BASE}/999999/forwarding/", data={"forward_to": "ext@example.com"},
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 404


@pytest.mark.django_db
def test_set_forwarding_invalid_forward_to_is_422(admin_auth):
    mb = _mailbox()
    resp = Client().post(
        f"{BASE}/{mb.id}/forwarding/", data={"forward_to": "not-an-email"},
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 422


@pytest.mark.django_db
def test_set_forwarding_mailcow_error_is_502(admin_auth, monkeypatch):
    import apps.mail.views as views_mod
    monkeypatch.setattr(views_mod, "MailcowClient", _RaisingMailcowClient)

    mb = _mailbox()
    resp = Client().post(
        f"{BASE}/{mb.id}/forwarding/", data={"forward_to": "ext@example.com"},
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 502
