"""Общие помощники тестов домена access.

Токены собираются настоящим ``jwt.encode`` против ``settings.JWT_SECRET`` —
тот же стиль, что в ``apps/contracts/tests/helpers.py``.
"""

from __future__ import annotations

import json

import jwt as pyjwt
from django.conf import settings
from django.test import Client

BASE = "/api/access/v1"


def token(**over) -> str:
    claims = {
        "user_id": 7, "username": "u", "email": "u@htq.test",
        "is_staff": False, "is_superuser": False, "is_admin": False,
        "token_type": "access", "iat": 1, "exp": 9_999_999_999,
        "iss": "htqweb-auth", "sub": "7",
        **over,
    }
    return pyjwt.encode(claims, settings.JWT_SECRET, algorithm="HS256")


def staff_token(**over) -> str:
    """Админ платформы «широкого» толка: is_staff, но НЕ суперпользователь.

    Существует ради одной проверки: каталог ролей ему править нельзя (§4.1).
    """
    return token(user_id=8, sub="8", is_staff=True, is_admin=True, **over)


def superuser_token(**over) -> str:
    return token(user_id=9, sub="9", is_staff=True, is_superuser=True,
                 is_admin=True, **over)


def auth(tok: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {tok}"}


def put_json(client: Client, path: str, body, **extra):
    return client.put(path, data=json.dumps(body, default=str),
                      content_type="application/json", **extra)


def post_json(client: Client, path: str, body, **extra):
    return client.post(path, data=json.dumps(body, default=str),
                       content_type="application/json", **extra)


def patch_json(client: Client, path: str, body, **extra):
    return client.patch(path, data=json.dumps(body, default=str),
                        content_type="application/json", **extra)
