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


# ── Глубина ролей ───────────────────────────────────────────────────────────

#: Прежние уровни → пресеты глубины. Тесты, писавшиеся до перехода на глубину,
#: рассуждают в терминах read/write/admin; соответствие собрано здесь, чтобы
#: оно было видно в одном месте, а не размазано по вызовам.
LEVEL_PRESET = {"none": "none", "read": "view", "write": "edit", "admin": "full"}


def grant(role, node: str, level_or_preset: str = "full"):
    """Выдать роли глубину на узел. Принимает и прежний уровень, и пресет."""
    from apps.access import depth
    from apps.access.models import RolePermission

    preset = LEVEL_PRESET.get(level_or_preset, level_or_preset)
    row = RolePermission(role=role, node=node)
    row.set_flags(depth.flags_of(preset))
    row.save()
    return row


def assign(company_slug: str, user_id: int, node: str, level_or_preset: str = "full"):
    """Выдать ПОЛЬЗОВАТЕЛЮ право на узел в компании — роль плюс назначение.

    Появилась с задачей 4 блока I «Единая модель прав»: ручки переведённых
    аппок стоят под ``api_view(module=…, level=…)``, и почти каждому тесту,
    который дёргает их по HTTP, нужна ровно эта тройка — роль, глубина на
    узле, личное назначение в компании запроса. Живёт здесь, а не копией в
    каждом файле, и её зовут в том числе тесты СОСЕДНИХ аппок: их каталог
    ``tests`` выведен из-под правила «сосед только через interface»
    (``apps/core/tests/test_app_isolation.py`` пропускает пути с ``tests``),
    а модель прав принадлежит именно этой аппке.

    Идемпотентна по паре (узел, уровень): второй вызов с теми же аргументами
    переиспользует роль и назначение, а не роняет тест на уникальности кода.
    """
    from apps.access.models import Role, RoleAssignment, ScopeKind

    code = f"t-{node}-{level_or_preset}".replace(".", "-").replace("_", "-")
    role, created = Role.objects.get_or_create(
        code=code, defaults={"title": f"{node}: {level_or_preset}"})
    if created:
        grant(role, node, level_or_preset)
    RoleAssignment.objects.get_or_create(
        company_slug=company_slug, user_id=user_id, role=role,
        scope_kind=ScopeKind.COMPANY, scope_id=None)
    return role
