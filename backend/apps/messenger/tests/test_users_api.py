"""Контракт /api/messenger/v1/users/* — паритет с
``services/messenger/app/api/v1/users.py`` (5 регистраций: ingest×1 + me×2 +
search×2, workers/admin под-задача, PLAN.md §6.5, последняя под-задача
messenger).

Р2 (все три — см. apps/messenger/models.py докстринг файла): исходник читал/
писал ``chat_user_replicas``, которая здесь не портируется:

  * ``POST /users/ingest`` — admin-гейт сохранён (как в исходнике), но
    НИЧЕГО не сохраняет (нет целевой таблицы) — эхо-ответ.
  * ``GET  /users/me``     — отдаёт apps.users.interface.get_user_brief(...)
    вместо формы UserReplicaRead (first_name/last_name/avatar_url недоступны).
  * ``GET  /users/search`` — деградирует к пустому списку (открытый вопрос,
    см. отчёт задачи: реальный поиск по apps.users.User здесь невозможен без
    расширения apps.users.interface ИЛИ восстановления таблицы-реплики —
    оба запрещены).
"""
from __future__ import annotations

import pytest
from django.test import Client

from apps.users.models import User, UserStatus
from htqweb.authn.jwt import issue_token_pair

BASE = "/api/messenger/v1/users"


@pytest.fixture
def user(db):
    u = User.objects.create(
        username="msg-self", email="msg-self@htq.test", password="x",
        status=UserStatus.ACTIVE, first_name="Иван", last_name="Иванов",
    )
    u.set_password("S3cret!Pass1")
    u.save()
    return u


@pytest.fixture
def admin_user(db):
    u = User.objects.create(
        username="msg-users-admin", email="msg-users-admin@htq.test", password="x",
        status=UserStatus.ACTIVE, is_staff=True,
    )
    u.set_password("S3cret!Pass1")
    u.save()
    return u


@pytest.fixture
def auth(user):
    return {"HTTP_AUTHORIZATION": f"Bearer {issue_token_pair(user)['access']}"}


@pytest.fixture
def admin_auth(admin_user):
    return {"HTTP_AUTHORIZATION": f"Bearer {issue_token_pair(admin_user)['access']}"}


# ── POST /users/ingest — Р2, no-op, admin-gated ───────────────────────────


@pytest.mark.django_db
def test_ingest_requires_admin(auth):
    resp = Client().post(
        f"{BASE}/ingest",
        data='{"id": 1, "username": "x", "first_name": "", "last_name": "", "avatar_url": null, "is_active": true}',
        content_type="application/json",
        **auth,
    )
    assert resp.status_code == 403


@pytest.mark.django_db
def test_ingest_echoes_body_without_persisting(admin_auth):
    body = {
        "id": 42, "username": "ghost", "first_name": "F", "last_name": "L",
        "avatar_url": None, "is_active": True, "is_bot": False,
    }
    import json as _json
    resp = Client().post(f"{BASE}/ingest", data=_json.dumps(body), content_type="application/json", **admin_auth)

    assert resp.status_code == 201
    assert resp.json() == body


@pytest.mark.django_db
def test_ingest_invalid_body_422(admin_auth):
    resp = Client().post(f"{BASE}/ingest", data="{}", content_type="application/json", **admin_auth)
    assert resp.status_code == 422


# ── GET /users/me ──────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_me_returns_users_interface_brief(user, auth):
    resp = Client().get(f"{BASE}/me", **auth)
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == user.id
    assert body["username"] == "msg-self"
    assert body["full_name"] == "Иван Иванов"
    assert body["is_active"] is True


@pytest.mark.django_db
def test_me_requires_auth():
    resp = Client().get(f"{BASE}/me")
    assert resp.status_code == 401


@pytest.mark.django_db
def test_me_no_slash_variant(user, auth):
    resp = Client().get(f"{BASE}/me/", **auth)
    assert resp.status_code == 200


# ── GET /users/search — Р2 degradation ────────────────────────────────────


@pytest.mark.django_db
def test_search_always_returns_empty_list(user, auth):
    resp = Client().get(f"{BASE}/search?q=anything", **auth)
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.django_db
def test_search_requires_auth():
    resp = Client().get(f"{BASE}/search")
    assert resp.status_code == 401


@pytest.mark.django_db
def test_search_no_slash_variant(user, auth):
    resp = Client().get(f"{BASE}/search/", **auth)
    assert resp.status_code == 200
    assert resp.json() == []
