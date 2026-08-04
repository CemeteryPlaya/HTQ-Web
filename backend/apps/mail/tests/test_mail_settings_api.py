"""Настройки почтового сервера из интерфейса + самоподключение ящика.

Два контракта:

  GET/PUT /api/email/v1/mailboxes/settings/       — админ правит реквизиты
  POST    /api/email/v1/mailboxes/settings/test/  — кнопка «Проверить»
  GET/POST/DELETE /api/email/v1/accounts/connect-corporate/ — сотрудник сам

Ключевое, что здесь закреплено: правило слияния «пустое в БД = берём из
окружения», нечитаемость секрета наружу и ограничения самоподключения.
"""
from __future__ import annotations

import pytest
from django.test import Client, override_settings

from apps.mail.models import EmailAccount, MailServerConfig, ProvisionedMailbox
from apps.mail.services import mail_config
from apps.mail.services.crypto import crypto_service
from apps.users.models import User, UserStatus
from htqweb.authn.jwt import issue_token_pair

SETTINGS_URL = "/api/email/v1/mailboxes/settings/"
TEST_URL = "/api/email/v1/mailboxes/settings/test/"
CONNECT_URL = "/api/email/v1/accounts/connect-corporate/"


@pytest.fixture(autouse=True)
def _clear_config_cache():
    """Строка настроек кэшируется на 5 секунд — между тестами это протекало
    бы в соседний тест."""
    mail_config.invalidate()
    yield
    mail_config.invalidate()


def _user(db, **kw) -> User:
    defaults = dict(username="u1", email="u1@htq.test", password="x", status=UserStatus.ACTIVE)
    defaults.update(kw)
    u = User.objects.create(**defaults)
    u.set_password("Passw0rd!")
    u.save()
    return u


def _auth(user) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {issue_token_pair(user)['access']}"}


@pytest.fixture
def admin_auth(db):
    return _auth(_user(db, username="cfg-admin", email="cfg-admin@htq.test", is_staff=True))


@pytest.fixture
def user_auth(db):
    return _auth(_user(db, username="cfg-user", email="cfg-user@htq.test"))


def _put(admin_auth, **body):
    return Client().put(
        SETTINGS_URL, data=body, content_type="application/json", **admin_auth,
    )


# ── доступ ───────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_settings_require_admin(user_auth):
    assert Client().get(SETTINGS_URL, **user_auth).status_code == 403
    assert Client().put(SETTINGS_URL, data=b"{}", content_type="application/json",
                        **user_auth).status_code == 403


@pytest.mark.django_db
def test_connection_test_requires_admin(user_auth):
    resp = Client().post(TEST_URL, data=b"{}", content_type="application/json", **user_auth)
    assert resp.status_code == 403


# ── чтение ───────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_get_shows_env_values_when_nothing_overridden(admin_auth):
    with override_settings(MAILCOW_DOMAIN="htq.group", IMAP_HOST="mail-tunnel", IMAP_PORT=1143):
        body = Client().get(SETTINGS_URL, **admin_auth).json()

    # в БД пусто — значит «наследуем»
    assert body["value"]["domain"] == ""
    assert body["value"]["imap_host"] == ""
    # но действует то, что пришло из окружения
    assert body["effective"]["domain"] == "htq.group"
    assert body["effective"]["imap_host"] == "mail-tunnel"
    assert body["effective"]["imap_port"] == 1143
    assert body["overridden"] == []


@pytest.mark.django_db
def test_get_marks_overridden_fields(admin_auth):
    _put(admin_auth, imap_host="mail.htq.group")
    with override_settings(IMAP_HOST="mail-tunnel"):
        body = Client().get(SETTINGS_URL, **admin_auth).json()

    assert body["effective"]["imap_host"] == "mail.htq.group"
    assert "imap_host" in body["overridden"]


# ── запись ───────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_put_saves_and_takes_effect_immediately(admin_auth):
    """Кэш строки живёт 5 секунд — без сброса админ увидел бы старое значение
    сразу после сохранения и решил, что форма не работает."""
    with override_settings(IMAP_HOST="", MAILCOW_DOMAIN=""):
        resp = _put(admin_auth, domain="htq.group", imap_host="mail-tunnel", imap_port=1143)
        assert resp.status_code == 200
        assert resp.json()["effective"]["imap_host"] == "mail-tunnel"
        # и следующий независимый запрос видит то же самое
        assert mail_config.get_config().imap_host == "mail-tunnel"


@pytest.mark.django_db
def test_put_normalizes_domain_typos(admin_auth):
    """Ту же опечатку («@htq.group», URL панели) делают и в форме, и в .env —
    чистка одна и та же."""
    assert _put(admin_auth, domain="@htq.group").json()["effective"]["domain"] == "htq.group"
    assert _put(admin_auth, domain="https://mail.htq.group/").json()["effective"]["domain"] \
        == "mail.htq.group"
    assert _put(admin_auth, domain="i.ivanov@htq.group").json()["effective"]["domain"] \
        == "htq.group"


@pytest.mark.django_db
def test_clearing_a_field_falls_back_to_env(admin_auth):
    _put(admin_auth, imap_host="mail.htq.group")
    with override_settings(IMAP_HOST="mail-tunnel"):
        assert mail_config.get_config().imap_host == "mail.htq.group"
        body = _put(admin_auth, imap_host="").json()

    assert body["effective"]["imap_host"] == "mail-tunnel"
    assert "imap_host" not in body["overridden"]


@pytest.mark.django_db
def test_false_overrides_true_from_env(admin_auth):
    """Ради этого случая булевы поля в БД nullable: обычный BooleanField не
    отличил бы «выключено» от «не задано»."""
    with override_settings(IMAP_SSL=True):
        assert mail_config.get_config().imap_ssl is True
        _put(admin_auth, imap_ssl=False)
        assert mail_config.get_config().imap_ssl is False


@pytest.mark.django_db
def test_partial_update_leaves_other_fields_alone(admin_auth):
    _put(admin_auth, imap_host="mail-tunnel", imap_port=1143)
    _put(admin_auth, domain="htq.group")

    row = MailServerConfig.objects.get(pk=MailServerConfig.SINGLETON_PK)
    assert row.imap_host == "mail-tunnel"
    assert row.imap_port == 1143


@pytest.mark.django_db
def test_sync_folders_accept_a_list(admin_auth):
    body = _put(admin_auth, sync_folders=["INBOX", "Sent Items"]).json()
    assert body["effective"]["sync_folders"] == ["INBOX", "Sent Items"]


@pytest.mark.django_db
def test_invalid_provisioner_is_422(admin_auth):
    resp = _put(admin_auth, provisioner="carrier-pigeon")
    assert resp.status_code == 422


@pytest.mark.django_db
def test_only_one_config_row_ever_exists(admin_auth):
    _put(admin_auth, imap_host="a")
    _put(admin_auth, imap_host="b")
    assert MailServerConfig.objects.count() == 1


# ── секрет ───────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_api_key_is_stored_encrypted_and_never_returned(admin_auth):
    body = _put(admin_auth, mailcow_api_key="super-secret-key").json()

    assert body["mailcow_api_key_set"] is True
    assert "super-secret-key" not in str(body)

    row = MailServerConfig.objects.get(pk=MailServerConfig.SINGLETON_PK)
    assert row.encrypted_mailcow_api_key != "super-secret-key"
    assert crypto_service.decrypt(row.encrypted_mailcow_api_key) == "super-secret-key"
    assert mail_config.get_config().mailcow_api_key == "super-secret-key"


@pytest.mark.django_db
def test_empty_api_key_means_leave_as_is(admin_auth):
    """Форма не знает текущего секрета, поэтому пустая строка не должна его
    затирать — иначе любое сохранение формы разлогинивало бы Mailcow."""
    _put(admin_auth, mailcow_api_key="keep-me")
    _put(admin_auth, imap_host="mail-tunnel", mailcow_api_key="")

    assert mail_config.get_config().mailcow_api_key == "keep-me"


@pytest.mark.django_db
def test_null_api_key_clears_the_override(admin_auth):
    _put(admin_auth, mailcow_api_key="stored-key")
    with override_settings(MAILCOW_API_KEY="env-key"):
        _put(admin_auth, mailcow_api_key=None)
        assert mail_config.get_config().mailcow_api_key == "env-key"


# ── кнопка «Проверить» ───────────────────────────────────────────────────

@pytest.mark.django_db
def test_connection_test_returns_structured_report(admin_auth, monkeypatch):
    from apps.mail.services import connection_check

    def _boom(*a, **kw):
        raise OSError("[Errno 111] Connection refused")
    monkeypatch.setattr(connection_check.socket, "create_connection", _boom)

    with override_settings(MAILCOW_DOMAIN="htq.group", MAIL_PROVISIONER="imap",
                           IMAP_HOST="mail-tunnel", IMAP_PORT=1143):
        resp = Client().post(TEST_URL, data={"timeout": 1},
                             content_type="application/json", **admin_auth)

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    keys = [s["key"] for s in body["steps"]]
    assert "config" in keys and "imap_port" in keys
    port_step = next(s for s in body["steps"] if s["key"] == "imap_port")
    assert port_step["status"] == "fail"
    assert port_step["hint"]


# ── самоподключение ──────────────────────────────────────────────────────

class _AcceptingProvisioner:
    name = "imap"
    can_list_remote = False
    can_create = False
    requires_existing_mailbox = True

    def __init__(self, accept: bool = True):
        self.accept = accept

    def verify(self, *, address: str, password: str):
        return (True, None) if self.accept else (False, "AUTHENTICATIONFAILED")


@pytest.fixture
def self_service_on(monkeypatch, admin_auth):
    """Включить режим и подменить проверку учётки."""
    def _install(accept: bool = True):
        _put(admin_auth, domain="htq.group", imap_host="mail-tunnel", allow_self_service=True)
        from apps.mail.services import self_service
        monkeypatch.setattr(self_service, "get_provisioner", lambda: _AcceptingProvisioner(accept))
    return _install


@pytest.mark.django_db
def test_self_connect_is_refused_while_disabled(user_auth, admin_auth):
    _put(admin_auth, domain="htq.group", imap_host="mail-tunnel", allow_self_service=False)
    resp = Client().post(CONNECT_URL, data={"address": "u@htq.group", "password": "x"},
                         content_type="application/json", **user_auth)
    assert resp.status_code == 403


@pytest.mark.django_db
def test_self_connect_links_mailbox_and_creates_account(db, user_auth, self_service_on):
    self_service_on()
    user = User.objects.get(username="cfg-user")

    resp = Client().post(CONNECT_URL, data={"address": "cfg.user@htq.group", "password": "S3cret!"},
                         content_type="application/json", **user_auth)

    assert resp.status_code == 201
    mb = ProvisionedMailbox.objects.get(address="cfg.user@htq.group")
    assert mb.user_id == user.id
    assert crypto_service.decrypt(mb.encrypted_smtp_app_password) == "S3cret!"
    # и ящик сразу виден в разделе «Почта»
    assert EmailAccount.objects.filter(user_id=user.id, type="corporate").exists()


@pytest.mark.django_db
def test_self_connect_rejects_foreign_domain(user_auth, self_service_on):
    self_service_on()
    resp = Client().post(CONNECT_URL, data={"address": "me@gmail.com", "password": "x"},
                         content_type="application/json", **user_auth)
    assert resp.status_code == 400
    assert "htq.group" in resp.json()["detail"]


@pytest.mark.django_db
def test_self_connect_rejects_wrong_password_without_creating_a_row(user_auth, self_service_on):
    """Нерабочая привязка хуже её отсутствия — она молча ломает и
    синхронизацию, и отправку."""
    self_service_on(accept=False)
    resp = Client().post(CONNECT_URL, data={"address": "cfg.user@htq.group", "password": "nope"},
                         content_type="application/json", **user_auth)

    assert resp.status_code == 400
    assert not ProvisionedMailbox.objects.filter(address="cfg.user@htq.group").exists()


@pytest.mark.django_db
def test_self_connect_cannot_steal_another_users_mailbox(db, user_auth, self_service_on):
    """Знание пароля от общего ящика не должно позволять увести привязку."""
    self_service_on()
    ProvisionedMailbox.objects.create(
        user_id=999, local_part="shared", domain="htq.group", address="shared@htq.group",
    )
    resp = Client().post(CONNECT_URL, data={"address": "shared@htq.group", "password": "S3cret!"},
                         content_type="application/json", **user_auth)

    assert resp.status_code == 409
    assert ProvisionedMailbox.objects.get(address="shared@htq.group").user_id == 999


@pytest.mark.django_db
def test_reconnecting_own_mailbox_updates_the_password(db, user_auth, self_service_on):
    self_service_on()
    Client().post(CONNECT_URL, data={"address": "cfg.user@htq.group", "password": "old"},
                  content_type="application/json", **user_auth)
    Client().post(CONNECT_URL, data={"address": "cfg.user@htq.group", "password": "new"},
                  content_type="application/json", **user_auth)

    mb = ProvisionedMailbox.objects.get(address="cfg.user@htq.group")
    assert crypto_service.decrypt(mb.encrypted_smtp_app_password) == "new"
    assert ProvisionedMailbox.objects.filter(address="cfg.user@htq.group").count() == 1


@pytest.mark.django_db
def test_self_connect_info_tells_the_user_what_is_allowed(user_auth, self_service_on):
    self_service_on()
    body = Client().get(CONNECT_URL, **user_auth).json()

    assert body["allowed"] is True
    assert body["domain"] == "htq.group"
    assert body["mailbox"] is None
    # реквизиты инфраструктуры обычному пользователю не отдаются
    assert "imap_host" not in body


@pytest.mark.django_db
def test_self_disconnect_detaches_without_touching_the_server(db, user_auth, self_service_on):
    self_service_on()
    Client().post(CONNECT_URL, data={"address": "cfg.user@htq.group", "password": "S3cret!"},
                  content_type="application/json", **user_auth)

    resp = Client().delete(CONNECT_URL, **user_auth)

    assert resp.status_code == 204
    mb = ProvisionedMailbox.objects.get(address="cfg.user@htq.group")
    # строка остаётся следом для админа, ящик на сервере не удаляется
    assert mb.status == "archived"
    assert not EmailAccount.objects.get(user_id=mb.user_id).is_active


@pytest.mark.django_db
def test_self_disconnect_without_a_mailbox_is_404(user_auth):
    assert Client().delete(CONNECT_URL, **user_auth).status_code == 404
