"""Длины полей профиля: 400/422 вместо 500.

``PATCH profile/me`` принимает multipart и клал значения в модель напрямую,
без единой проверки длины. Значение длиннее колонки доходило до Postgres и
возвращалось клиенту как ``DataError`` -> 500, хотя это обычный плохой
запрос. То же самое на админских ручках, только через Pydantic.

Маска телефона на фронте шлёт максимум ``+7 (700) 483-55-81`` — 18 символов,
так что в норме ни один из этих путей не срабатывает. Тесты держат
поведение для всего, что приходит мимо формы.
"""

from __future__ import annotations

import json

import pytest

from apps.users.models import User, UserStatus
from htqweb.authn.jwt import issue_token_pair

BASE = "/api/users/v1"

# users.User.phone — varchar(30).
PHONE_MAX = 30
MASKED_PHONE = "+7 (700) 483-55-81"     # 18 символов, то, что шлёт PhoneInput


def _mk(username: str, **fields) -> User:
    user = User.objects.create(username=username, password="x",
                               status=UserStatus.ACTIVE, **fields)
    user.set_password("S3cret!")
    user.save()
    return user


def _auth(user) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {issue_token_pair(user)['access']}"}


@pytest.fixture
def user(db):
    return _mk("fieldlimits", email="fieldlimits@htq.test",
               first_name="Поле", last_name="Лимитов")


@pytest.fixture
def admin(db):
    return _mk("limitadmin", email="limitadmin@htq.test", is_superuser=True,
               is_staff=True)


# ── multipart PATCH profile/me ──────────────────────────────────────────

@pytest.mark.django_db
def test_masked_phone_is_saved_as_is(user, client):
    """Ровно то, что шлёт PhoneInput, проходит без вопросов."""
    resp = client.patch(
        f"{BASE}/profile/me",
        data=_multipart({"phone": MASKED_PHONE}),
        content_type="multipart/form-data; boundary=BOUNDARY",
        **_auth(user),
    )
    assert resp.status_code == 200
    user.refresh_from_db()
    assert user.phone == MASKED_PHONE


@pytest.mark.django_db
def test_overlong_phone_is_400_not_500(user, client):
    resp = client.patch(
        f"{BASE}/profile/me",
        data=_multipart({"phone": "7" * (PHONE_MAX + 1)}),
        content_type="multipart/form-data; boundary=BOUNDARY",
        **_auth(user),
    )
    assert resp.status_code == 400
    assert "phone" in resp.json()["detail"]
    user.refresh_from_db()
    assert user.phone == ""          # ничего не записалось


@pytest.mark.django_db
def test_phone_exactly_at_the_limit_is_accepted(user, client):
    exact = "7" * PHONE_MAX
    resp = client.patch(
        f"{BASE}/profile/me",
        data=_multipart({"phone": exact}),
        content_type="multipart/form-data; boundary=BOUNDARY",
        **_auth(user),
    )
    assert resp.status_code == 200
    user.refresh_from_db()
    assert user.phone == exact


@pytest.mark.django_db
def test_overlong_name_is_400_too(user, client):
    """Проверка общая для всех CharField профиля, а не только для телефона."""
    resp = client.patch(
        f"{BASE}/profile/me",
        data=_multipart({"display_name": "я" * 200}),   # колонка 100
        content_type="multipart/form-data; boundary=BOUNDARY",
        **_auth(user),
    )
    assert resp.status_code == 400
    assert "display_name" in resp.json()["detail"]


@pytest.mark.django_db
def test_bio_has_no_limit_because_it_is_a_textfield(user, client):
    """``bio`` — TextField без max_length, и проверка обязана его пропустить,
    а не выдумать ограничение."""
    resp = client.patch(
        f"{BASE}/profile/me",
        data=_multipart({"bio": "б" * 5000}),
        content_type="multipart/form-data; boundary=BOUNDARY",
        **_auth(user),
    )
    assert resp.status_code == 200


# ── админские ручки (Pydantic) ──────────────────────────────────────────

@pytest.mark.django_db
def test_admin_create_rejects_overlong_phone(admin, client):
    resp = client.post(
        f"{BASE}/admin/users/",
        data=json.dumps({
            "username": "newguy", "email": "newguy@htq.test",
            "password": "S3cretPass!", "phone": "7" * (PHONE_MAX + 1),
        }),
        content_type="application/json",
        **_auth(admin),
    )
    assert resp.status_code == 422
    assert not User.objects.filter(username="newguy").exists()


@pytest.mark.django_db
def test_admin_create_accepts_a_masked_phone(admin, client):
    resp = client.post(
        f"{BASE}/admin/users/",
        data=json.dumps({
            "username": "maskguy", "email": "maskguy@htq.test",
            "password": "S3cretPass!", "phone": MASKED_PHONE,
        }),
        content_type="application/json",
        **_auth(admin),
    )
    assert resp.status_code == 201
    assert User.objects.get(username="maskguy").phone == MASKED_PHONE


@pytest.mark.django_db
def test_admin_update_rejects_overlong_phone(admin, user, client):
    resp = client.patch(
        f"{BASE}/admin/users/{user.id}/",
        data=json.dumps({"phone": "7" * (PHONE_MAX + 1)}),
        content_type="application/json",
        **_auth(admin),
    )
    assert resp.status_code == 422
    user.refresh_from_db()
    assert user.phone == ""


def _multipart(fields: dict[str, str]) -> bytes:
    """Минимальный multipart-энкодер.

    ``Client.patch`` не кодирует dict в multipart (в отличие от ``post``), а
    вьюха читает именно multipart — так что тело собирается руками.
    """
    boundary = "BOUNDARY"
    parts = []
    for name, value in fields.items():
        parts.append(
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
            f"{value}\r\n"
        )
    parts.append(f"--{boundary}--\r\n")
    return "".join(parts).encode("utf-8")
