"""Shared test helpers for the tasks domain.

The other apps repeat their ``_token``/``_auth_header`` pair in each test
file. With ~15 route groups to cover that would be a dozen copies of the
same six lines, so the tasks tests share one module instead. This is not a
break with the "duplicate per service" rule in CLAUDE.md — that rule
protects independently-deployed FastAPI services, and (as the root
``conftest.py`` spells out) it does not apply inside the single Django
process.

Not named ``test_*.py``, so pytest does not collect it (``pytest.ini`` sets
``python_files = test_*.py``).
"""

from __future__ import annotations

import json

import jwt as pyjwt
from django.conf import settings
from django.test import Client

BASE = "/api/tasks/v1"


def token(**over) -> str:
    """A valid access token. Claims match ``htqweb.authn`` expectations —
    issuer ``htqweb-auth``, ``token_type='access'`` (see CLAUDE.md's JWT
    contract)."""
    claims = {
        "user_id": 7, "username": "u", "email": "u@htq.test",
        "is_staff": False, "is_superuser": False, "is_admin": False,
        "token_type": "access", "iat": 1, "exp": 9_999_999_999,
        "iss": "htqweb-auth", "sub": "7",
        **over,
    }
    return pyjwt.encode(claims, settings.JWT_SECRET, algorithm="HS256")


def admin_token(**over) -> str:
    return token(user_id=9, sub="9", is_admin=True, **over)


def auth(tok: str | None = None) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {tok or token()}"}


def post_json(client: Client, path: str, body: dict, **extra):
    return client.post(path, data=json.dumps(body),
                       content_type="application/json", **extra)


def patch_json(client: Client, path: str, body: dict, **extra):
    return client.patch(path, data=json.dumps(body),
                        content_type="application/json", **extra)


def put_json(client: Client, path: str, body: dict, **extra):
    return client.put(path, data=json.dumps(body),
                      content_type="application/json", **extra)
