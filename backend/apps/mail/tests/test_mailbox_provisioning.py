"""Ящик, созданный на сайте, должен появиться на почтовом сервере.

Раньше ``mailbox_service`` писал только локальную строку — это и был баг
«создание почт на сайте не создаёт почты в почтовом ящике». Здесь
проверяется, что каждая операция доходит до почтового сервера, что отказ
сервера виден админу, и что в неконфигурированном окружении поведение
осталось прежним (обратная совместимость).

Живой сети нет: подменяется ``get_provisioner`` в ``mailbox_service``.
"""
from __future__ import annotations

from datetime import timedelta

import pytest
from django.test import Client, override_settings
from django.utils import timezone

from apps.mail.models import (
    EmailAccount,
    MailboxStatus,
    OAuthToken,
    ProvisionedMailbox,
)
from apps.mail.services import mailbox_service as mbx_svc
from apps.mail.services.crypto import crypto_service
from apps.mail.services.provisioning.base import ProvisioningError
from apps.users.models import User, UserStatus
from htqweb.authn.jwt import issue_token_pair

BASE = "/api/email/v1/mailboxes"


@pytest.fixture
def admin_auth(db):
    u = User.objects.create(
        username="prov-admin", email="prov-admin@htq.test", password="x",
        status=UserStatus.ACTIVE, is_staff=True,
    )
    u.set_password("Adm1n!Pass")
    u.save()
    return {"HTTP_AUTHORIZATION": f"Bearer {issue_token_pair(u)['access']}"}


class _RecordingProvisioner:
    name = "mailcow"
    can_list_remote = True
    can_create = True
    requires_existing_mailbox = False

    def __init__(self, fail_on: str | None = None, app_password: bool = False):
        self.calls: list[tuple] = []
        self.fail_on = fail_on
        self.app_password = app_password

    def _record(self, action, **kw):
        self.calls.append((action, kw))
        if self.fail_on == action:
            raise ProvisioningError(f"server refused {action}")

    def create(self, **kw):
        self._record("create", **kw)

    def update(self, **kw):
        self._record("update", **kw)

    def reset_password(self, **kw):
        self._record("reset_password", **kw)

    def set_active(self, **kw):
        self._record("set_active", **kw)

    def delete(self, **kw):
        self._record("delete", **kw)

    def verify(self, **kw):
        return True, None


class _VerifyOnlyProvisioner(_RecordingProvisioner):
    """Сервер без админ-API: ящик уже существует, его только проверяют."""

    name = "imap"
    can_list_remote = False
    can_create = False
    requires_existing_mailbox = True


@pytest.fixture
def use_provisioner(monkeypatch):
    def _install(provisioner):
        monkeypatch.setattr(mbx_svc, "get_provisioner", lambda: provisioner)
        return provisioner
    return _install


def _post_create(admin_auth, **body):
    return Client().post(
        f"{BASE}/", data=body or {}, content_type="application/json", **admin_auth,
    )


# ── create ───────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_create_reaches_the_mail_server(admin_auth, use_provisioner):
    provisioner = use_provisioner(_RecordingProvisioner())
    with override_settings(MAILCOW_DOMAIN="htq.group"):
        resp = _post_create(admin_auth, local_part="j.doe", password="MyStr0ngPass!", quota_mb=2048)

    assert resp.status_code == 201
    action, kw = provisioner.calls[0]
    assert action == "create"
    assert kw["address"] == "j.doe@htq.group"
    assert kw["password"] == "MyStr0ngPass!"
    assert kw["quota_mb"] == 2048


@pytest.mark.django_db
def test_create_stores_password_encrypted_for_sync_and_send(admin_auth, use_provisioner):
    """Без сохранённого пароля не работают ни синхронизация, ни отправка —
    раньше поле не заполнял никто."""
    use_provisioner(_RecordingProvisioner())
    with override_settings(MAILCOW_DOMAIN="htq.group"):
        resp = _post_create(admin_auth, local_part="j.doe", password="MyStr0ngPass!")

    mb = ProvisionedMailbox.objects.get(id=resp.json()["id"])
    assert mb.encrypted_smtp_app_password
    assert mb.encrypted_smtp_app_password != "MyStr0ngPass!"     # именно зашифрован
    assert crypto_service.decrypt(mb.encrypted_smtp_app_password) == "MyStr0ngPass!"


@pytest.mark.django_db
def test_create_with_user_makes_the_mailbox_visible_in_mail_section(admin_auth, use_provisioner):
    """Ящик без EmailAccount не видно ни в списке аккаунтов, ни в почте —
    он оставался «мёртвой» строкой в админке."""
    use_provisioner(_RecordingProvisioner())
    with override_settings(MAILCOW_DOMAIN="htq.group"):
        _post_create(admin_auth, local_part="j.doe", user_id=42)

    account = EmailAccount.objects.get(user_id=42)
    assert account.address == "j.doe@htq.group"
    assert account.type == "corporate"
    assert account.provider == "mailcow"
    assert account.is_active is True
    assert account.is_default is True        # первый аккаунт пользователя


@pytest.mark.django_db
def test_create_without_user_makes_no_account(admin_auth, use_provisioner):
    """Общий ящик (info@) никому не принадлежит — показывать его некому."""
    use_provisioner(_RecordingProvisioner())
    with override_settings(MAILCOW_DOMAIN="htq.group"):
        _post_create(admin_auth, local_part="info")

    assert EmailAccount.objects.count() == 0


@pytest.mark.django_db
def test_corporate_mailbox_does_not_steal_an_existing_default(admin_auth, use_provisioner):
    """У пользователя уже настроен личный ящик по умолчанию — выдача
    корпоративного не должна молча переключать ему адрес отправителя."""
    use_provisioner(_RecordingProvisioner())
    token = OAuthToken.objects.create(
        user_id=42, provider="google", provider_account_id="g-42",
        encrypted_access_token="x", expires_at=timezone.now() + timedelta(hours=1),
    )
    EmailAccount.objects.create(
        user_id=42, type="personal", provider="google", address="me@gmail.com",
        oauth_token=token, is_default=True,
    )

    with override_settings(MAILCOW_DOMAIN="htq.group"):
        _post_create(admin_auth, local_part="j.doe", user_id=42)

    corporate = EmailAccount.objects.get(user_id=42, type="corporate")
    assert corporate.is_default is False
    assert EmailAccount.objects.get(user_id=42, type="personal").is_default is True


@pytest.mark.django_db
def test_create_failure_returns_502_and_leaves_a_visible_error_row(admin_auth, use_provisioner):
    """Отказ сервера не должен выглядеть как «ничего не произошло»:
    строка остаётся со статусом error, чтобы админ её увидел и починил."""
    use_provisioner(_RecordingProvisioner(fail_on="create"))
    with override_settings(MAILCOW_DOMAIN="htq.group"):
        resp = _post_create(admin_auth, local_part="j.doe", password="MyStr0ngPass!")

    assert resp.status_code == 502
    body = resp.json()
    assert "server refused create" in body["detail"]
    assert body["mailbox"]["status"] == "error"

    mb = ProvisionedMailbox.objects.get(address="j.doe@htq.group")
    assert mb.status == "error"
    assert "server refused create" in mb.last_error


@pytest.mark.django_db
def test_create_failure_does_not_store_password_or_account(admin_auth, use_provisioner):
    use_provisioner(_RecordingProvisioner(fail_on="create"))
    with override_settings(MAILCOW_DOMAIN="htq.group"):
        _post_create(admin_auth, local_part="j.doe", password="x", user_id=42)

    mb = ProvisionedMailbox.objects.get(address="j.doe@htq.group")
    assert not mb.encrypted_smtp_app_password
    assert EmailAccount.objects.count() == 0


# ── режим без админ-API (IMAP) ───────────────────────────────────────────

@pytest.mark.django_db
def test_imap_mode_rejects_taken_address_instead_of_renaming(admin_auth, use_provisioner):
    """С Mailcow занятый адрес тихо становится i.ivanov2 — сервер заведёт
    любой. На IMAP-сервере адрес обязан совпасть с существующим ящиком,
    поэтому переименование дало бы заведомо нерабочую привязку."""
    ProvisionedMailbox.objects.create(
        local_part="i.ivanov", domain="htq.group", address="i.ivanov@htq.group",
    )
    use_provisioner(_VerifyOnlyProvisioner())
    with override_settings(MAILCOW_DOMAIN="htq.group"):
        resp = _post_create(admin_auth, local_part="i.ivanov", password="S3cret!")

    assert resp.status_code == 409
    assert resp.json()["detail"] == "Mailbox i.ivanov@htq.group already exists"
    assert ProvisionedMailbox.objects.filter(address="i.ivanov2@htq.group").count() == 0


@pytest.mark.django_db
def test_mailcow_mode_still_deduplicates_address(admin_auth, use_provisioner):
    """Обратная совместимость: старое поведение для сервера с админ-API."""
    ProvisionedMailbox.objects.create(
        local_part="i.ivanov", domain="htq.group", address="i.ivanov@htq.group",
    )
    use_provisioner(_RecordingProvisioner())
    with override_settings(MAILCOW_DOMAIN="htq.group"):
        resp = _post_create(admin_auth, local_part="i.ivanov")

    assert resp.status_code == 201
    assert resp.json()["address"] == "i.ivanov2@htq.group"


@pytest.mark.django_db
def test_imap_account_gets_imap_provider(admin_auth, use_provisioner):
    use_provisioner(_VerifyOnlyProvisioner())
    with override_settings(
        MAILCOW_DOMAIN="htq.group", MAIL_PROVISIONER="imap", IMAP_HOST="mail-tunnel",
    ):
        _post_create(admin_auth, local_part="j.doe", password="S3cret!", user_id=42)

    assert EmailAccount.objects.get(user_id=42).provider == "imap"


# ── reset-password / archive / restore / delete ──────────────────────────

@pytest.mark.django_db
def test_reset_password_reaches_the_server_and_updates_stored_secret(admin_auth, use_provisioner):
    provisioner = use_provisioner(_RecordingProvisioner())
    mb = ProvisionedMailbox.objects.create(
        local_part="a", domain="htq.group", address="a@htq.group",
        encrypted_smtp_app_password=crypto_service.encrypt("old"),
    )
    resp = Client().post(
        f"{BASE}/{mb.id}/reset-password/", data={"new_password": "Br4ndNew!"},
        content_type="application/json", **admin_auth,
    )

    assert resp.status_code == 200
    action, kw = provisioner.calls[0]
    assert action == "reset_password"
    assert kw["new_password"] == "Br4ndNew!"
    mb.refresh_from_db()
    assert crypto_service.decrypt(mb.encrypted_smtp_app_password) == "Br4ndNew!"


@pytest.mark.django_db
def test_reset_password_failure_is_502_not_a_silent_success(admin_auth, use_provisioner):
    """Иначе админ выдал бы сотруднику пароль, которого на сервере нет."""
    use_provisioner(_RecordingProvisioner(fail_on="reset_password"))
    mb = ProvisionedMailbox.objects.create(
        local_part="a", domain="htq.group", address="a@htq.group",
        encrypted_smtp_app_password=crypto_service.encrypt("old"),
    )
    resp = Client().post(
        f"{BASE}/{mb.id}/reset-password/", data=b"{}",
        content_type="application/json", **admin_auth,
    )

    assert resp.status_code == 502
    mb.refresh_from_db()
    # Старый пароль остался нетронутым — он всё ещё верен для сервера.
    assert crypto_service.decrypt(mb.encrypted_smtp_app_password) == "old"


@pytest.mark.django_db
def test_archive_disables_mailbox_on_the_server(admin_auth, use_provisioner):
    provisioner = use_provisioner(_RecordingProvisioner())
    mb = ProvisionedMailbox.objects.create(
        local_part="a", domain="htq.group", address="a@htq.group",
    )
    resp = Client().post(f"{BASE}/{mb.id}/archive/", **admin_auth)

    assert resp.status_code == 200
    assert provisioner.calls == [("set_active", {"address": "a@htq.group", "active": False})]


@pytest.mark.django_db
def test_restore_re_enables_mailbox_on_the_server(admin_auth, use_provisioner):
    provisioner = use_provisioner(_RecordingProvisioner())
    mb = ProvisionedMailbox.objects.create(
        local_part="a", domain="htq.group", address="a@htq.group",
        status=MailboxStatus.ARCHIVED,
    )
    Client().post(f"{BASE}/{mb.id}/restore/", **admin_auth)

    assert provisioner.calls == [("set_active", {"address": "a@htq.group", "active": True})]


@pytest.mark.django_db
def test_delete_removes_mailbox_from_the_server(admin_auth, use_provisioner):
    provisioner = use_provisioner(_RecordingProvisioner())
    mb = ProvisionedMailbox.objects.create(
        local_part="a", domain="htq.group", address="a@htq.group",
        status=MailboxStatus.ARCHIVED,
    )
    resp = Client().delete(f"{BASE}/{mb.id}/", **admin_auth)

    assert resp.status_code == 204
    assert provisioner.calls == [("delete", {"address": "a@htq.group"})]


@pytest.mark.django_db
def test_archive_still_succeeds_locally_when_server_is_down(admin_auth, use_provisioner):
    """Иначе ящик уволенного сотрудника нельзя было бы закрыть, пока
    почтовый сервер недоступен. Расхождение фиксируется в last_error и
    всплывёт в сверке."""
    use_provisioner(_RecordingProvisioner(fail_on="set_active"))
    mb = ProvisionedMailbox.objects.create(
        local_part="a", domain="htq.group", address="a@htq.group",
    )
    resp = Client().post(f"{BASE}/{mb.id}/archive/", **admin_auth)

    assert resp.status_code == 200
    mb.refresh_from_db()
    assert mb.status == "archived"
    assert "server refused set_active" in mb.last_error


@pytest.mark.django_db
def test_update_failure_keeps_local_change_and_records_divergence(admin_auth, use_provisioner):
    use_provisioner(_RecordingProvisioner(fail_on="update"))
    mb = ProvisionedMailbox.objects.create(
        local_part="a", domain="htq.group", address="a@htq.group", quota_mb=1024,
    )
    resp = Client().patch(
        f"{BASE}/{mb.id}/", data={"quota_mb": 4096},
        content_type="application/json", **admin_auth,
    )

    assert resp.status_code == 200
    mb.refresh_from_db()
    assert mb.quota_mb == 4096
    assert "server refused update" in mb.last_error


@pytest.mark.django_db
def test_successful_update_clears_a_previous_error(admin_auth, use_provisioner):
    use_provisioner(_RecordingProvisioner())
    mb = ProvisionedMailbox.objects.create(
        local_part="a", domain="htq.group", address="a@htq.group",
        quota_mb=1024, last_error="старая ошибка",
    )
    Client().patch(
        f"{BASE}/{mb.id}/", data={"quota_mb": 4096},
        content_type="application/json", **admin_auth,
    )

    mb.refresh_from_db()
    assert mb.last_error is None


# ── обратная совместимость ───────────────────────────────────────────────

@pytest.mark.django_db
def test_unconfigured_environment_behaves_exactly_as_before(admin_auth):
    """Без MAILCOW_API_URL и IMAP_HOST выбирается NoopProvisioner: ящик
    создаётся локально, наружу никто не ходит, ответ прежний."""
    with override_settings(
        MAILCOW_DOMAIN="htq.group", MAIL_PROVISIONER="auto",
        MAILCOW_API_URL="", MAILCOW_API_KEY="", IMAP_HOST="",
    ):
        resp = _post_create(admin_auth, first_name="Иван", last_name="Иванов")

    assert resp.status_code == 201
    body = resp.json()
    assert body["address"] == "i.ivanov@htq.group"
    assert body["status"] == "active"
    assert body["last_error"] is None
    assert len(body["generated_password"]) >= 16


@pytest.mark.django_db
def test_unconfigured_environment_still_deduplicates_the_address(admin_auth):
    """Сторож регрессии: «не переименовывать занятый адрес» — правило ТОЛЬКО
    для сервера, где ящик обязан существовать (IMAP). Ненастроенное
    окружение ящиков на сервере не имеет, поэтому подбор свободного адреса
    там должен работать как раньше."""
    ProvisionedMailbox.objects.create(
        local_part="i.ivanov", domain="htq.group", address="i.ivanov@htq.group",
    )
    with override_settings(
        MAILCOW_DOMAIN="htq.group", MAIL_PROVISIONER="auto",
        MAILCOW_API_URL="", MAILCOW_API_KEY="", IMAP_HOST="",
    ):
        resp = _post_create(admin_auth, local_part="i.ivanov")

    assert resp.status_code == 201
    assert resp.json()["address"] == "i.ivanov2@htq.group"


@pytest.mark.django_db
def test_unconfigured_domain_still_returns_the_same_500(admin_auth):
    with override_settings(MAILCOW_DOMAIN=""):
        resp = _post_create(admin_auth)
    assert resp.status_code == 500
    assert resp.json()["detail"] == "MAILCOW_DOMAIN not configured"
