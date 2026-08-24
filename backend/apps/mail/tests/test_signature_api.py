"""Подпись сотрудника в письмах.

Подпись живёт ПРИ АККАУНТЕ, а не при пользователе: у человека может быть и
корпоративный ящик, и личный, и подписывать клиентское письмо тем же, чем
личное, он не захочет.

Главное, что здесь проверяется, — владение: подпись уходит получателям писем
от имени сотрудника, поэтому вписать её в чужой аккаунт не должно быть
возможно ни при каких условиях.
"""
from __future__ import annotations

import pytest
from django.test import Client

from apps.mail.models import AccountType, EmailAccount, ProvisionedMailbox
from apps.users.models import User, UserStatus
from htqweb.authn.jwt import issue_token_pair

BASE = "/api/email/v1/accounts"


def _user(username: str) -> User:
    u = User.objects.create(
        username=username, email=f"{username}@htq.group", password="x",
        status=UserStatus.ACTIVE,
    )
    u.set_password("S3cret!")
    u.save()
    return u


def _auth(user: User) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {issue_token_pair(user)['access']}"}


def _account(user: User) -> EmailAccount:
    mb = ProvisionedMailbox.objects.create(
        user_id=user.id, local_part=user.username, domain="htq.group",
        address=user.email, status="active",
    )
    return EmailAccount.objects.create(
        user_id=user.id, type=AccountType.CORPORATE, provider="mailcow",
        address=user.email, mailbox=mb, is_active=True,
    )


@pytest.mark.django_db
def test_signature_starts_empty_and_is_returned_with_the_account():
    user = _user("amirov")
    account = _account(user)

    resp = Client().get(f"{BASE}/", **_auth(user))
    assert resp.status_code == 200
    row = next(a for a in resp.json() if a["id"] == account.id)
    assert row["signature"] == ""


@pytest.mark.django_db
def test_employee_saves_their_signature():
    user = _user("amirov")
    account = _account(user)
    signature = "Руслан Амиров\nHi-Tech Group\n+7 700 000-00-00"

    resp = Client().patch(
        f"{BASE}/{account.id}/signature/", data={"signature": signature},
        content_type="application/json", **_auth(user),
    )

    assert resp.status_code == 200
    assert resp.json()["signature"] == signature
    account.refresh_from_db()
    assert account.signature == signature


@pytest.mark.django_db
def test_signature_keeps_its_line_breaks_and_trailing_blank_line():
    """Хвостовой перевод строки — осознанный отступ до цитаты, а не мусор:
    «прибираться» тут значит спорить с автором подписи."""
    user = _user("amirov")
    account = _account(user)

    Client().patch(
        f"{BASE}/{account.id}/signature/", data={"signature": "Руслан\nHTQ\n"},
        content_type="application/json", **_auth(user),
    )

    account.refresh_from_db()
    assert account.signature == "Руслан\nHTQ\n"


@pytest.mark.django_db
def test_signature_can_be_cleared():
    user = _user("amirov")
    account = _account(user)
    account.signature = "старая"
    account.save(update_fields=["signature"])

    resp = Client().patch(
        f"{BASE}/{account.id}/signature/", data={"signature": ""},
        content_type="application/json", **_auth(user),
    )

    assert resp.status_code == 200
    account.refresh_from_db()
    assert account.signature == ""


@pytest.mark.django_db
def test_nobody_can_write_a_signature_into_someone_elses_account():
    """Подпись уходит получателям от имени владельца ящика — чужую подделать
    нельзя. Отвечаем 404, а не 403: чужой аккаунт для этого пользователя
    просто не существует, и подтверждать его наличие незачем."""
    owner = _user("amirov")
    intruder = _user("petrov")
    account = _account(owner)

    resp = Client().patch(
        f"{BASE}/{account.id}/signature/", data={"signature": "не моя"},
        content_type="application/json", **_auth(intruder),
    )

    assert resp.status_code == 404
    account.refresh_from_db()
    assert account.signature == ""


@pytest.mark.django_db
def test_signature_endpoint_requires_authentication():
    user = _user("amirov")
    account = _account(user)

    resp = Client().patch(
        f"{BASE}/{account.id}/signature/", data={"signature": "x"},
        content_type="application/json",
    )

    assert resp.status_code == 401


@pytest.mark.django_db
def test_signature_longer_than_the_limit_is_rejected():
    user = _user("amirov")
    account = _account(user)

    resp = Client().patch(
        f"{BASE}/{account.id}/signature/", data={"signature": "x" * 4001},
        content_type="application/json", **_auth(user),
    )

    assert resp.status_code == 422
    account.refresh_from_db()
    assert account.signature == ""
