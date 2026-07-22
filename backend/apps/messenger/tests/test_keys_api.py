"""Контракт /api/messenger/v1/keys/* — паритет с
``services/messenger/app/api/v1/keys.py`` (2 эндпойнта):

  POST /keys/            — upload_keys (201, upsert по (user_id, device_id))
  GET  /keys/{user_id}   — get_user_keys (все устройства пользователя)

Оба — обычный JWT-пользователь (``get_current_user`` исходника). ``POST``
пишет ключи ВЫЗЫВАЮЩЕГО (``user.user_id`` из токена, не из тела) — ``GET``
не ограничен своим профилем (любой авторизованный может прочитать публичный
ключ любого пользователя, буквальный контракт исходника: ``user_id`` из пути,
без сверки с ``user.user_id``).
"""
from __future__ import annotations

import json

import pytest
from django.test import Client

from apps.messenger.models import UserKey
from apps.users.models import User, UserStatus
from htqweb.authn.jwt import issue_token_pair

BASE = "/api/messenger/v1/keys"


@pytest.fixture
def user(db):
    u = User.objects.create(username="key-user", email="key-user@htq.test", password="x", status=UserStatus.ACTIVE)
    u.set_password("S3cret!Pass1")
    u.save()
    return u


@pytest.fixture
def other_user(db):
    u = User.objects.create(username="key-other", email="key-other@htq.test", password="x", status=UserStatus.ACTIVE)
    u.set_password("S3cret!Pass1")
    u.save()
    return u


@pytest.fixture
def auth(user):
    return {"HTTP_AUTHORIZATION": f"Bearer {issue_token_pair(user)['access']}"}


@pytest.fixture
def other_auth(other_user):
    return {"HTTP_AUTHORIZATION": f"Bearer {issue_token_pair(other_user)['access']}"}


def _payload(**overrides):
    body = {
        "device_id": "device-1",
        "public_identity_key": "idkey",
        "signed_pre_key": "prekey",
        "signature": "sig",
    }
    body.update(overrides)
    return body


# ── auth ─────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_upload_keys_requires_jwt():
    resp = Client().post(f"{BASE}/", data=json.dumps(_payload()), content_type="application/json")
    assert resp.status_code == 401


@pytest.mark.django_db
def test_get_user_keys_requires_jwt(user):
    resp = Client().get(f"{BASE}/{user.id}")
    assert resp.status_code == 401


# ── POST /keys/ ──────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_upload_keys_creates_new(user, auth):
    resp = Client().post(f"{BASE}/", data=json.dumps(_payload()), content_type="application/json", **auth)
    assert resp.status_code == 201
    body = resp.json()
    assert body["user_id"] == user.id
    assert body["device_id"] == "device-1"
    assert body["public_identity_key"] == "idkey"
    assert body["signed_pre_key"] == "prekey"
    assert body["signature"] == "sig"
    assert UserKey.objects.filter(user_id=user.id, device_id="device-1").exists()


@pytest.mark.django_db
def test_upload_keys_upserts_existing_device(user, auth):
    Client().post(f"{BASE}/", data=json.dumps(_payload()), content_type="application/json", **auth)
    resp = Client().post(
        f"{BASE}/",
        data=json.dumps(_payload(public_identity_key="idkey-2", signed_pre_key="prekey-2", signature="sig-2")),
        content_type="application/json", **auth,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["public_identity_key"] == "idkey-2"
    assert UserKey.objects.filter(user_id=user.id).count() == 1


@pytest.mark.django_db
def test_upload_keys_different_devices_coexist(user, auth):
    Client().post(f"{BASE}/", data=json.dumps(_payload(device_id="dev-a")), content_type="application/json", **auth)
    Client().post(f"{BASE}/", data=json.dumps(_payload(device_id="dev-b")), content_type="application/json", **auth)
    assert UserKey.objects.filter(user_id=user.id).count() == 2


@pytest.mark.django_db
def test_upload_keys_writes_own_user_id_not_body(user, other_user, auth):
    """Тело не несёт ``user_id`` (контракт исходника: ``UserKeyCreate`` без
    этого поля) — записывается ``request.token.user_id``."""
    resp = Client().post(f"{BASE}/", data=json.dumps(_payload()), content_type="application/json", **auth)
    assert resp.json()["user_id"] == user.id
    assert not UserKey.objects.filter(user_id=other_user.id).exists()


@pytest.mark.django_db
def test_upload_keys_missing_field_422(auth):
    body = _payload()
    del body["signature"]
    resp = Client().post(f"{BASE}/", data=json.dumps(body), content_type="application/json", **auth)
    assert resp.status_code == 422


# ── GET /keys/{user_id} ───────────────────────────────────────────────────

@pytest.mark.django_db
def test_get_user_keys_returns_all_devices(user, auth):
    UserKey.objects.create(
        user_id=user.id, device_id="dev-a", public_identity_key="a", signed_pre_key="b", signature="c",
    )
    UserKey.objects.create(
        user_id=user.id, device_id="dev-b", public_identity_key="a2", signed_pre_key="b2", signature="c2",
    )
    resp = Client().get(f"{BASE}/{user.id}", **auth)
    assert resp.status_code == 200
    body = resp.json()
    assert {k["device_id"] for k in body} == {"dev-a", "dev-b"}


@pytest.mark.django_db
def test_get_user_keys_empty_list_when_none(user, auth):
    resp = Client().get(f"{BASE}/{user.id}", **auth)
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.django_db
def test_get_user_keys_any_authenticated_caller_can_read_others(user, other_user, other_auth):
    """Буквальный контракт исходника: ``GET /{user_id}`` не сверяет
    ``user_id`` пути с вызывающим — любой авторизованный видит публичный
    ключ любого пользователя."""
    UserKey.objects.create(
        user_id=user.id, device_id="dev-a", public_identity_key="a", signed_pre_key="b", signature="c",
    )
    resp = Client().get(f"{BASE}/{user.id}", **other_auth)
    assert resp.status_code == 200
    assert len(resp.json()) == 1
