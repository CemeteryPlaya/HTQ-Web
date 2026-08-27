"""Кто из сотрудников остался без рабочей почты — список для администратора.

Обратная сторона подсказки «введите пароль»: та адресует проблему сотруднику
по одному, эта показывает всю картину разом. Проверяется главным образом то,
кого в списке быть НЕ должно: список, куда попадают люди без проблемы, админ
перестанет открывать через неделю.

Причина у каждой строки своя, потому что действия разные: завести ящик,
свести бесхозный с владельцем или сходить к сотруднику за паролем.
"""
from __future__ import annotations

import pytest
from django.test import Client, override_settings

from apps.mail.models import MailboxStatus, ProvisionedMailbox
from apps.mail.services.crypto import crypto_service
from apps.users.models import User, UserStatus
from htqweb.authn.jwt import issue_token_pair

URL = "/api/email/v1/mailboxes/coverage/"

#: Настройки, при которых режим резолвится в mailcow: ``awaits_password``
#: читает режим из настроек, и с одним лишь доменом получил бы "none".
MAILCOW_ENV = {
    "MAILCOW_DOMAIN": "htq.group",
    "MAILCOW_API_URL": "https://mailcow.test/api/v1",
    "MAILCOW_API_KEY": "test-key",
    "MAIL_PROVISIONER": "mailcow",
}


def _user(email: str, *, active: bool = True, **kw) -> User:
    return User.objects.create(
        username=email.partition("@")[0], email=email, password="x",
        status=UserStatus.ACTIVE if active else UserStatus.SUSPENDED, **kw,
    )


def _admin_auth() -> dict:
    # Адрес НЕ корпоративный намеренно: админ с @htq.group и без ящика попал
    # бы в собственный список, и каждый тест пришлось бы писать с оговоркой.
    admin = _user("cov-admin@htq.local", is_staff=True, is_superuser=True)
    return {"HTTP_AUTHORIZATION": f"Bearer {issue_token_pair(admin)['access']}"}


def _mailbox(address: str, **kw) -> ProvisionedMailbox:
    kw.setdefault("local_part", address.partition("@")[0])
    kw.setdefault("domain", "htq.group")
    kw.setdefault("status", MailboxStatus.ACTIVE)
    return ProvisionedMailbox.objects.create(address=address, **kw)


def _working(address: str, user_id: int) -> ProvisionedMailbox:
    """Ящик, которым реально можно пользоваться: привязан и пароль есть."""
    return _mailbox(
        address, user_id=user_id,
        encrypted_smtp_app_password=crypto_service.encrypt("MailPass!"),
    )


def _coverage(auth: dict, **env) -> dict:
    settings = {**MAILCOW_ENV}
    settings.update(env)
    with override_settings(**settings):
        resp = Client().get(URL, **auth)
    assert resp.status_code == 200, resp.content
    return resp.json()


def _emails(body: dict) -> set[str]:
    return {row["email"] for row in body["users"]}


def _reason(body: dict, email: str) -> str | None:
    for row in body["users"]:
        if row["email"] == email:
            return row["reason"]
    return None


# ── кто в списке ─────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_employee_without_a_mailbox_is_listed():
    auth = _admin_auth()
    _user("ruslan.amirov@htq.group")

    body = _coverage(auth)
    assert _reason(body, "ruslan.amirov@htq.group") == "no_mailbox"


@pytest.mark.django_db
def test_ownerless_mailbox_is_a_different_problem():
    """Ящик на сервере есть, сверка его ещё не связала. Заводить второй такой
    было бы дублем — админу надо свести, а не создать."""
    auth = _admin_auth()
    user = _user("ruslan.amirov@htq.group")
    _mailbox("ruslan.amirov@htq.group", user_id=None)

    body = _coverage(auth)
    assert _reason(body, "ruslan.amirov@htq.group") == "not_linked"
    assert body["users"][0]["user_id"] == user.id


@pytest.mark.django_db
def test_mailbox_without_a_password_is_a_third_problem():
    """Ящик привязан, но читать нечем: это решает сотрудник, а не админ."""
    auth = _admin_auth()
    user = _user("ruslan.amirov@htq.group")
    _mailbox("ruslan.amirov@htq.group", user_id=user.id)

    body = _coverage(auth)
    assert _reason(body, "ruslan.amirov@htq.group") == "awaiting_password"


# ── кого в списке быть не должно ─────────────────────────────────────────

@pytest.mark.django_db
def test_working_mail_is_not_a_problem():
    auth = _admin_auth()
    user = _user("ruslan.amirov@htq.group")
    _working("ruslan.amirov@htq.group", user.id)

    assert "ruslan.amirov@htq.group" not in _emails(_coverage(auth))


@pytest.mark.django_db
def test_personal_email_is_not_listed():
    """Корпоративный ящик из @gmail.com платформа не делает и не должна —
    строка про такого человека была бы задачей, которую нельзя выполнить."""
    auth = _admin_auth()
    _user("someone@gmail.com")

    assert "someone@gmail.com" not in _emails(_coverage(auth))


@pytest.mark.django_db
def test_inactive_employee_is_not_listed():
    """Ушедшему из компании ящик больше не нужен."""
    auth = _admin_auth()
    _user("ruslan.amirov@htq.group", active=False)

    assert "ruslan.amirov@htq.group" not in _emails(_coverage(auth))


@pytest.mark.django_db
def test_renamed_employee_keeps_their_mailbox():
    """Адрес сменили, ящик остался привязан по владельцу и работает. Искать
    только по адресу — значит записать такого в «без почты» и завести ему
    второй ящик."""
    auth = _admin_auth()
    user = _user("ruslan.amirov@htq.group")
    _working("r.amirov@htq.group", user.id)

    assert "ruslan.amirov@htq.group" not in _emails(_coverage(auth))


# ── контекст для интерфейса и права ──────────────────────────────────────

@pytest.mark.django_db
def test_bulk_creation_is_offered_only_where_it_works():
    """На голом IMAP платформа ящики не создаёт — кнопка «завести пачкой»
    была бы обманом, и интерфейс узнаёт об этом отсюда."""
    auth = _admin_auth()
    _user("ruslan.amirov@htq.group")

    assert _coverage(auth)["can_create_remotely"] is True
    imap = _coverage(auth, MAIL_PROVISIONER="imap", IMAP_HOST="mail.htq.group")
    assert imap["can_create_remotely"] is False
    # Список при этом тот же: проблема есть в обоих режимах, разнится способ.
    assert _emails(imap) == {"ruslan.amirov@htq.group"}


@pytest.mark.django_db
def test_ordinary_user_cannot_read_the_list():
    """Список — это карта того, у кого почта не защищена паролем платформы.
    Обычному сотруднику её видеть незачем."""
    user = _user("ruslan.amirov@htq.group")
    with override_settings(**MAILCOW_ENV):
        resp = Client().get(
            URL, HTTP_AUTHORIZATION=f"Bearer {issue_token_pair(user)['access']}",
        )
    assert resp.status_code == 403


@pytest.mark.django_db
def test_no_corporate_domain_means_no_list():
    """Домен не настроен — «корпоративный адрес» не определён, и гадать
    платформа не станет."""
    auth = _admin_auth()
    _user("ruslan.amirov@htq.group")

    body = _coverage(auth, MAILCOW_DOMAIN="", MAIL_PROVISIONER="none",
                     MAILCOW_API_URL="", MAILCOW_API_KEY="")
    assert body["users"] == []
