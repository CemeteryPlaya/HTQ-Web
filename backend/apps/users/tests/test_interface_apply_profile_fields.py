"""Белый список ``apply_profile_fields`` — вторая линия обороны.

Смысл тестов не в том, «работает ли setattr», а в том, что через эту дверь
НЕЛЬЗЯ протолкнуть логин, пароль или роли, даже если вызывающий очень захочет.

Спека: docs/superpowers/specs/2026-08-25-hr-identity-sync-design.md §7.
"""
from __future__ import annotations

import pytest

from apps.users import interface as users_interface
from apps.users.models import User, UserStatus


@pytest.fixture
def user(db):
    row = User.objects.create(
        username="ivan", email="ivan@htq.test", password="x",
        first_name="Иван", last_name="Петров", status=UserStatus.ACTIVE,
    )
    row.set_password("S3cret!Pass1")
    row.save()
    return row


@pytest.mark.django_db
def test_applies_whitelisted_fields(user):
    users_interface.apply_profile_fields(
        user_id=user.id,
        fields={"phone": "+7 705 000-00-00", "patronymic": "Сергеевич"},
        actor_id=1,
    )
    user.refresh_from_db()
    assert user.phone == "+7 705 000-00-00"
    assert user.patronymic == "Сергеевич"


@pytest.mark.django_db
@pytest.mark.parametrize("field,value", [
    ("email", "other@htq.test"),
    ("username", "hacked"),
    ("password", "plaintext"),
    ("is_staff", True),
    ("is_superuser", True),
    ("status", "blocked"),
])
def test_rejects_fields_outside_whitelist(user, field, value):
    with pytest.raises(ValueError):
        users_interface.apply_profile_fields(
            user_id=user.id, fields={field: value}, actor_id=1,
        )
    user.refresh_from_db()
    assert user.email == "ivan@htq.test"
    assert user.username == "ivan"
    assert user.is_staff is False


@pytest.mark.django_db
def test_mixed_payload_applies_nothing(user):
    """Одно запрещённое поле рубит ВЕСЬ вызов — иначе заявка применилась бы
    частично, и подтверждающий не узнал бы, какая её часть не доехала."""
    with pytest.raises(ValueError):
        users_interface.apply_profile_fields(
            user_id=user.id,
            fields={"phone": "+7 705 000-00-00", "is_superuser": True},
            actor_id=1,
        )
    user.refresh_from_db()
    assert user.phone == ""
    assert user.is_superuser is False


@pytest.mark.django_db
def test_unknown_user_raises(db):
    with pytest.raises(users_interface.UserNotFound):
        users_interface.apply_profile_fields(
            user_id=999999, fields={"phone": "1"}, actor_id=1,
        )


@pytest.mark.django_db
def test_empty_fields_is_noop(user):
    result = users_interface.apply_profile_fields(
        user_id=user.id, fields={}, actor_id=1,
    )
    assert result["id"] == user.id


@pytest.mark.django_db
def test_profile_for_hr_carries_bio_and_avatar(user):
    user.bio = "Инженер"
    user.avatar_url = "/api/media/v1/files/abc"
    user.save()

    profile = users_interface.get_user_profile_for_hr(user.id)

    assert profile["bio"] == "Инженер"
    assert profile["avatar_url"] == "/api/media/v1/files/abc"
    assert profile["patronymic"] == ""


@pytest.mark.django_db
def test_profile_for_hr_unknown_user_is_none(db):
    assert users_interface.get_user_profile_for_hr(999999) is None
