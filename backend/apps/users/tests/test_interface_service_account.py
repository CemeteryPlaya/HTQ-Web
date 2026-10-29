"""``apps.users.interface.ensure_service_account`` — служебная учётка соседа
(автор файлов КП с портала tender, T3.4): войти ею нельзя, повтор не
заводит вторую."""

from __future__ import annotations

import pytest
from django.test import Client

from apps.users import interface
from apps.users.models import User, UserStatus

pytestmark = pytest.mark.django_db


def test_creates_an_inactive_account_without_a_password():
    user_id = interface.ensure_service_account("tender-portal", first_name="Поставщик",
                                               last_name="(портал)")
    user = User.objects.get(pk=user_id)
    assert user.username == "tender-portal"
    assert user.status == UserStatus.SUSPENDED and not user.is_active
    assert not user.has_usable_password()
    assert user.email.endswith("@service.invalid")
    assert (user.first_name, user.last_name) == ("Поставщик", "(портал)")
    assert interface.get_user_brief(user_id)["full_name"]


def test_is_idempotent_and_keeps_the_existing_row():
    first = interface.ensure_service_account("tender-portal", first_name="Поставщик",
                                             last_name="(портал)")
    User.objects.filter(pk=first).update(first_name="Изменено")
    again = interface.ensure_service_account("tender-portal", first_name="Другое",
                                             last_name="Имя")
    assert again == first
    assert User.objects.filter(username="tender-portal").count() == 1
    assert User.objects.get(pk=first).first_name == "Изменено"


def test_cannot_log_in():
    interface.ensure_service_account("tender-portal", first_name="Поставщик",
                                     last_name="(портал)")
    for password in ("", "tender-portal", "!"):
        resp = Client().post("/api/users/v1/token/", {"username": "tender-portal",
                                                      "password": password},
                             content_type="application/json")
        assert resp.status_code in (400, 401, 422), resp.content
