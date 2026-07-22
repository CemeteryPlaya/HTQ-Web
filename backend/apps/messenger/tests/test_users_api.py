"""Контракт /api/messenger/v1/users/* — паритет с
``services/messenger/app/api/v1/users.py`` (5 регистраций: ingest×1 + me×2 +
search×2, workers/admin под-задача, PLAN.md §6.5, последняя под-задача
messenger).

Р2 (ingest/me — см. apps/messenger/models.py докстринг файла): исходник
читал/писал ``chat_user_replicas``, которая здесь не портируется:

  * ``POST /users/ingest`` — admin-гейт сохранён (как в исходнике), но
    НИЧЕГО не сохраняет (нет целевой таблицы) — эхо-ответ.
  * ``GET  /users/me``     — отдаёт apps.users.interface.get_user_brief(...)
    вместо формы UserReplicaRead (first_name/last_name/avatar_url недоступны).
  * ``GET  /users/search`` — БОЛЬШЕ НЕ деградация: apps.users.interface
    получила list_users_brief (задача Р3 без S2S), search/me/ingest вьюха
    отдаёт реальные результаты по apps.users.User (username/first_name/
    last_name/email), исключая текущего пользователя и неактивных.
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


# ── GET /users/search — real results via apps.users.interface ────────────


@pytest.fixture
def other(db):
    u = User.objects.create(
        username="msg-other", email="msg-other@htq.test", password="x",
        status=UserStatus.ACTIVE, first_name="Petr", last_name="Petrov",
    )
    u.set_password("S3cret!Pass1")
    u.save()
    return u


@pytest.fixture
def suspended_other(db):
    u = User.objects.create(
        username="msg-suspended", email="msg-suspended@htq.test", password="x",
        status=UserStatus.SUSPENDED, first_name="Sus", last_name="Pended",
    )
    u.set_password("S3cret!Pass1")
    u.save()
    return u


@pytest.mark.django_db
def test_search_requires_auth():
    resp = Client().get(f"{BASE}/search")
    assert resp.status_code == 401


@pytest.mark.django_db
def test_search_no_slash_variant(user, other, auth):
    resp = Client().get(f"{BASE}/search/", **auth)
    assert resp.status_code == 200
    assert {u["id"] for u in resp.json()} == {other.id}


@pytest.mark.django_db
def test_search_returns_matching_active_users(user, other, auth):
    resp = Client().get(f"{BASE}/search?q=petrov", **auth)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["id"] == other.id
    assert body[0]["full_name"] == "Petr Petrov"


@pytest.mark.django_db
def test_search_excludes_current_user(user, auth):
    resp = Client().get(f"{BASE}/search?q=Иван", **auth)
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.django_db
def test_search_excludes_suspended_users(user, suspended_other, auth):
    resp = Client().get(f"{BASE}/search?q=Sus", **auth)
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.django_db
def test_search_empty_query_returns_active_users(user, other, auth):
    resp = Client().get(f"{BASE}/search", **auth)
    assert resp.status_code == 200
    assert {u["id"] for u in resp.json()} == {other.id}


@pytest.mark.django_db
def test_search_no_match_returns_empty(user, other, auth):
    resp = Client().get(f"{BASE}/search?q=zzznomatchzzz", **auth)
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.django_db
def test_search_limit_respected(user, auth):
    for i in range(3):
        u = User.objects.create(
            username=f"msg-many-{i}", email=f"msg-many-{i}@htq.test", password="x",
            status=UserStatus.ACTIVE, first_name="Many", last_name=f"User{i}",
        )
        u.set_password("S3cret!Pass1")
        u.save()

    resp = Client().get(f"{BASE}/search?q=Many&limit=2", **auth)
    assert resp.status_code == 200
    assert len(resp.json()) == 2


@pytest.mark.django_db
def test_search_limit_zero_422(user, auth):
    resp = Client().get(f"{BASE}/search?limit=0", **auth)
    assert resp.status_code == 422


@pytest.mark.django_db
def test_search_limit_over_max_422(user, auth):
    resp = Client().get(f"{BASE}/search?limit=101", **auth)
    assert resp.status_code == 422
