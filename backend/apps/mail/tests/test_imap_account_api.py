"""Подключение произвольного аккаунта по IMAP — третий способ добавить почту.

Легко перепутать с ``connect-corporate``: там сервер один и задан админом,
домен обязан совпасть с корпоративным, и создаётся ``ProvisionedMailbox``.
Здесь пользователь указывает СВОЙ сервер, домен любой, а платформа лишь
читает и отправляет через этот ящик. Тесты закрепляют обе половины различия.

Живой сети нет: подменяется ``ImapClient._open_connection``.
"""
from __future__ import annotations

import pytest
from django.test import Client

from apps.mail.models import EmailAccount, ImapAccountSettings, OAuthToken
from apps.mail.services import imap_account_service
from apps.mail.services import imap_client as imap_module
from apps.mail.services.crypto import crypto_service
from apps.users.models import User, UserStatus
from htqweb.authn.jwt import issue_token_pair

CONNECT = "/api/email/v1/accounts/connect-imap/"
SECRET = "S3cret!Pass"


class _FakeIMAP4:
    class error(Exception):
        pass

    def __init__(self, bad_password="wrong"):
        self._bad = bad_password
        self.logged_in = None

    def login(self, user, password):
        if password == self._bad:
            raise _FakeIMAP4.error("AUTHENTICATIONFAILED")
        self.logged_in = (user, password)
        return ("OK", [b"ok"])

    def list(self):
        return ("OK", [b'(\\HasNoChildren) "/" "INBOX"'])

    def close(self):
        return None

    def logout(self):
        return ("BYE", [b"bye"])


@pytest.fixture
def fake_imap(monkeypatch):
    holder = {}

    def _install(**kw):
        fake = _FakeIMAP4(**kw)
        holder["fake"] = fake
        monkeypatch.setattr(imap_module.ImapClient, "_open_connection", lambda self: fake)
        monkeypatch.setattr(imap_module.imaplib.IMAP4, "error", _FakeIMAP4.error, raising=False)
        return fake
    _install.holder = holder  # type: ignore[attr-defined]
    return _install


@pytest.fixture
def user(db):
    u = User.objects.create(
        username="imapper", email="imapper@htq.test", password="x", status=UserStatus.ACTIVE,
    )
    u.set_password("Passw0rd!")
    u.save()
    return u


@pytest.fixture
def auth(user):
    return {"HTTP_AUTHORIZATION": f"Bearer {issue_token_pair(user)['access']}"}


BODY = {
    "address": "me@example.com",
    "password": SECRET,
    "imap_host": "imap.example.com",
    "imap_port": 993,
    "imap_ssl": True,
    "smtp_host": "smtp.example.com",
    "smtp_port": 587,
    "smtp_starttls": True,
}


def _connect(auth, **overrides):
    return Client().post(
        CONNECT, data={**BODY, **overrides}, content_type="application/json", **auth,
    )


# ── подсказка настроек ───────────────────────────────────────────────────

@pytest.mark.django_db
def test_hint_returns_known_provider_settings(auth):
    body = Client().get(f"{CONNECT}?address=me@gmail.com", **auth).json()
    assert body["imap_host"] == "imap.gmail.com"
    assert body["known"] is True
    assert body["guessed"] is False


@pytest.mark.django_db
def test_hint_guesses_for_unknown_domain_and_says_so(auth):
    """Догадка часто верна, но выдавать её за факт нельзя — интерфейс должен
    показать, что значения нужно проверить."""
    body = Client().get(f"{CONNECT}?address=me@some-host.ru", **auth).json()
    assert body["imap_host"] == "imap.some-host.ru"
    assert body["known"] is False
    assert body["guessed"] is True


@pytest.mark.django_db
def test_hint_without_address_returns_blank_defaults(auth):
    body = Client().get(CONNECT, **auth).json()
    assert body["imap_host"] == ""
    assert body["imap_port"] == 993


@pytest.mark.django_db
def test_yandex_preset_uses_implicit_tls_for_smtp(auth):
    """У Яндекса submission — 465/SSL, а не 587/STARTTLS: подставить общий
    дефолт значило бы гарантированно не отправить письмо."""
    body = Client().get(f"{CONNECT}?address=me@yandex.ru", **auth).json()
    assert body["smtp_port"] == 465
    assert body["smtp_ssl"] is True
    assert body["smtp_starttls"] is False


# ── подключение ──────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_connect_creates_account_with_its_own_server(auth, user, fake_imap):
    fake_imap()
    resp = _connect(auth)

    assert resp.status_code == 201
    account = EmailAccount.objects.get(user_id=user.id, address="me@example.com")
    assert account.type == "personal"
    assert account.provider == "imap"
    assert account.oauth_token_id is None
    assert account.mailbox_id is None

    row = account.imap_settings
    assert row.imap_host == "imap.example.com"
    assert row.smtp_host == "smtp.example.com"
    assert crypto_service.decrypt(row.encrypted_password) == SECRET


@pytest.mark.django_db
def test_connect_verifies_credentials_before_writing_anything(auth, fake_imap):
    """Молча сохранённые неверные реквизиты выглядели бы как рабочее
    подключение и сломались бы позже, не на глазах у пользователя."""
    fake_imap()
    resp = _connect(auth, password="wrong")

    assert resp.status_code == 400
    # Отказ по паролю называется своим именем и подсказывает самую частую
    # причину, а не пересказывает техническую ошибку сервера.
    assert "отклонил логин или пароль" in resp.json()["detail"]
    assert EmailAccount.objects.count() == 0
    assert ImapAccountSettings.objects.count() == 0


@pytest.mark.django_db
def test_login_uses_username_when_it_differs_from_the_address(auth, fake_imap):
    """Бывает логин «ivanov» вместо «ivanov@example.com» — иначе вход не
    прошёл бы на таких серверах."""
    fake = fake_imap()
    _connect(auth, username="ivanov")

    assert fake.logged_in == ("ivanov", SECRET)


@pytest.mark.django_db
def test_login_falls_back_to_the_address(auth, fake_imap):
    fake = fake_imap()
    _connect(auth)
    assert fake.logged_in == ("me@example.com", SECRET)


@pytest.mark.django_db
def test_any_domain_is_allowed_unlike_corporate_self_service(auth, fake_imap):
    """Это личный ящик пользователя, а не ресурс платформы — ограничивать
    домен здесь нечем и незачем."""
    fake_imap()
    assert _connect(auth, address="me@gmail.com").status_code == 201


@pytest.mark.django_db
def test_duplicate_address_is_409(auth, fake_imap):
    fake_imap()
    _connect(auth)
    resp = _connect(auth)
    assert resp.status_code == 409
    assert EmailAccount.objects.count() == 1


@pytest.mark.django_db
def test_first_account_becomes_default(auth, user, fake_imap):
    fake_imap()
    _connect(auth)
    assert EmailAccount.objects.get(user_id=user.id).is_default is True


@pytest.mark.django_db
def test_second_account_does_not_steal_default(auth, user, fake_imap):
    fake_imap()
    _connect(auth)
    _connect(auth, address="other@example.com")

    accounts = EmailAccount.objects.filter(user_id=user.id).order_by("id")
    assert [a.is_default for a in accounts] == [True, False]


@pytest.mark.django_db
def test_requires_authentication():
    resp = Client().post(CONNECT, data=BODY, content_type="application/json")
    assert resp.status_code == 401


@pytest.mark.django_db
def test_invalid_address_is_422(auth):
    resp = _connect(auth, address="not-an-email")
    assert resp.status_code == 422


@pytest.mark.django_db
def test_missing_imap_host_is_422(auth):
    body = {k: v for k, v in BODY.items() if k != "imap_host"}
    resp = Client().post(CONNECT, data=body, content_type="application/json", **auth)
    assert resp.status_code == 422


# ── смена пароля ─────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_password_update_verifies_the_new_one(auth, user, fake_imap):
    fake_imap()
    account_id = _connect(auth).json()["id"]

    resp = Client().post(
        f"/api/email/v1/accounts/{account_id}/imap-password/",
        data={"password": "brand-new"}, content_type="application/json", **auth,
    )

    assert resp.status_code == 200
    row = EmailAccount.objects.get(id=account_id).imap_settings
    assert crypto_service.decrypt(row.encrypted_password) == "brand-new"


@pytest.mark.django_db
def test_password_update_rejects_a_password_the_server_refuses(auth, fake_imap):
    """Иначе синхронизация встала бы молча, с виду рабочим аккаунтом."""
    fake_imap()
    account_id = _connect(auth).json()["id"]

    resp = Client().post(
        f"/api/email/v1/accounts/{account_id}/imap-password/",
        data={"password": "wrong"}, content_type="application/json", **auth,
    )

    assert resp.status_code == 400
    row = EmailAccount.objects.get(id=account_id).imap_settings
    assert crypto_service.decrypt(row.encrypted_password) == SECRET


@pytest.mark.django_db
def test_cannot_change_password_of_someone_elses_account(db, auth, fake_imap):
    fake_imap()
    account_id = _connect(auth).json()["id"]

    other = User.objects.create(
        username="other", email="other@htq.test", password="x", status=UserStatus.ACTIVE,
    )
    other.set_password("Passw0rd!")
    other.save()
    other_auth = {"HTTP_AUTHORIZATION": f"Bearer {issue_token_pair(other)['access']}"}

    resp = Client().post(
        f"/api/email/v1/accounts/{account_id}/imap-password/",
        data={"password": "x"}, content_type="application/json", **other_auth,
    )
    assert resp.status_code == 404


# ── отключение ───────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_disconnect_removes_the_stored_credentials(auth, fake_imap):
    """Осиротевшая строка с зашифрованным паролем не нужна никому."""
    fake_imap()
    account_id = _connect(auth).json()["id"]
    assert ImapAccountSettings.objects.count() == 1

    resp = Client().delete(f"/api/email/v1/accounts/{account_id}/", **auth)

    assert resp.status_code == 204
    assert EmailAccount.objects.count() == 0
    assert ImapAccountSettings.objects.count() == 0


@pytest.mark.django_db
def test_disconnecting_imap_account_does_not_touch_oauth_accounts(db, auth, user, fake_imap):
    """Ветка revoke относится только к OAuth — для IMAP её быть не должно."""
    from django.utils import timezone
    from datetime import timedelta

    fake_imap()
    account_id = _connect(auth).json()["id"]
    token = OAuthToken.objects.create(
        user_id=user.id, provider="google", provider_account_id="g",
        encrypted_access_token="enc", expires_at=timezone.now() + timedelta(hours=1),
    )
    EmailAccount.objects.create(
        user_id=user.id, type="personal", provider="google",
        address="me@gmail.com", oauth_token=token,
    )

    Client().delete(f"/api/email/v1/accounts/{account_id}/", **auth)

    assert OAuthToken.objects.count() == 1
    assert EmailAccount.objects.filter(provider="google").count() == 1


# ── интеграция с синхронизацией и отправкой ──────────────────────────────

@pytest.mark.django_db
def test_sync_uses_the_accounts_own_server(auth, fake_imap):
    """Ходить за письмами этого ящика на корпоративный хост бессмысленно и
    опасно — при совпадении логинов попали бы в чужой ящик."""
    from apps.mail.services.sync import imap_sync

    fake_imap()
    account_id = _connect(auth).json()["id"]
    account = EmailAccount.objects.get(id=account_id)

    client = imap_sync.imap_client_for(account)
    assert client.config.host == "imap.example.com"
    assert client.config.port == 993
    assert imap_sync.resolve_credentials(account) == ("me@example.com", SECRET)


@pytest.mark.django_db
def test_send_uses_the_accounts_own_smtp(auth, fake_imap):
    from apps.mail.services.sender import corporate_smtp

    fake_imap()
    account_id = _connect(auth).json()["id"]
    account = EmailAccount.objects.get(id=account_id)

    assert corporate_smtp.account_smtp_target(account) == ("smtp.example.com", 587)
    password, error = corporate_smtp.resolve_app_password(account)
    assert error is None and password == SECRET


@pytest.mark.django_db
def test_smtp_falls_back_to_the_imap_host(auth, fake_imap):
    from apps.mail.services.sender import corporate_smtp

    fake_imap()
    account_id = _connect(auth, smtp_host="").json()["id"]
    account = EmailAccount.objects.get(id=account_id)

    assert corporate_smtp.account_smtp_target(account)[0] == "imap.example.com"


@pytest.mark.django_db
def test_poll_picks_up_imap_accounts(auth, user, fake_imap):
    """Иначе подключённый ящик просто не синхронизировался бы: webhook'ов у
    произвольного сервера нет, опрос — единственный источник писем."""
    from apps.mail.services.sync import imap_sync

    fake_imap()
    _connect(auth)

    assert "imap" in imap_sync.IMAP_PROVIDERS
    picked = EmailAccount.objects.filter(
        provider__in=imap_sync.IMAP_PROVIDERS, is_active=True, last_sync_at__isnull=True,
    )
    assert picked.count() == 1


# ── границы модели ───────────────────────────────────────────────────────

@pytest.mark.django_db
def test_personal_account_cannot_hold_both_oauth_and_imap(db, user):
    """CHECK-констрейнт: источник учётки ровно один, иначе непонятно, какой
    из них истина."""
    from django.db import IntegrityError, transaction
    from django.utils import timezone
    from datetime import timedelta

    token = OAuthToken.objects.create(
        user_id=user.id, provider="google", provider_account_id="g",
        encrypted_access_token="enc", expires_at=timezone.now() + timedelta(hours=1),
    )
    row = ImapAccountSettings.objects.create(
        imap_host="imap.example.com", username="u", encrypted_password="e",
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        EmailAccount.objects.create(
            user_id=user.id, type="personal", provider="imap",
            address="both@example.com", oauth_token=token, imap_settings=row,
        )


# ── диагностика ошибок ───────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expect", [
    ("IMAP connect failed (imap.htq.group:993): [Errno -2] Name or service not known",
     "не найден"),
    ("IMAP login failed for me: AUTHENTICATIONFAILED", "пароль приложения"),
    ("IMAP connect failed (h:993): timed out", "не ответил вовремя"),
    ("IMAP connect failed (h:993): [Errno 111] Connection refused", "порт"),
    ("IMAP connect failed (h:993): SSL: WRONG_VERSION_NUMBER", "шифрования"),
])
def test_failures_are_explained_in_actionable_terms(raw, expect):
    """«Name or service not known» ничего не говорит человеку, который просто
    хотел подключить почту, — а означает вполне конкретное: такого хоста нет,
    и надо спросить настоящий адрес, а не перебирать пароли."""
    message = imap_account_service.explain_failure(raw, "imap.htq.group")
    assert expect in message


def test_unknown_failure_is_passed_through_verbatim():
    """Неизвестную ошибку лучше показать как есть, чем подменить неверной
    догадкой о причине."""
    message = imap_account_service.explain_failure("странная ошибка сервера", "h")
    assert "странная ошибка сервера" in message


@pytest.mark.django_db
def test_dns_failure_names_the_host_that_was_not_found(auth, monkeypatch):
    monkeypatch.setattr(
        imap_module.ImapClient, "_open_connection",
        lambda self: (_ for _ in ()).throw(OSError("[Errno -2] Name or service not known")),
    )
    resp = _connect(auth, imap_host="imap.nonexistent.example")

    assert resp.status_code == 400
    assert "imap.nonexistent.example" in resp.json()["detail"]
    assert "не найден" in resp.json()["detail"]


# ── подсказка для корпоративного домена ──────────────────────────────────

@pytest.mark.django_db
def test_hint_prefers_the_configured_corporate_server(auth):
    """Гадать imap.<домен> там, где настоящий хост уже настроен админом, —
    прямой путь к ошибке «сервер не найден» на несуществующем адресе."""
    from apps.mail.models import MailServerConfig
    from apps.mail.services import mail_config

    MailServerConfig.objects.update_or_create(
        pk=MailServerConfig.SINGLETON_PK,
        defaults={"domain": "htq.group", "imap_host": "mail-tunnel",
                  "imap_port": 1143, "imap_ssl": False},
    )
    mail_config.invalidate()
    try:
        body = Client().get(f"{CONNECT}?address=someone@htq.group", **auth).json()
    finally:
        mail_config.invalidate()

    assert body["imap_host"] == "mail-tunnel"
    assert body["imap_port"] == 1143
    assert body["guessed"] is False
    assert body.get("corporate") is True
