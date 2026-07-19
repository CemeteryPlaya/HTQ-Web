"""Публичный API аппки users для ДРУГИХ аппок.

Единственный способ, которым сосед имеет право обращаться к users. Прямой
импорт apps.users.models / apps.users.services из другой аппки запрещён и
ловится тестом apps/core/tests/test_app_isolation.py.

Каждая функция начинается с require_service("users"): если аппка выключена,
вызывающий получит ServiceDisabled, который api_view превратит в 503-конверт
(а не в 500) — см. htqweb/http.py. Это тот же контракт, что и у
apps.cms.interface — см. его докстринг для полного объяснения.

Возвращаются только простые dict'ы, никогда ORM-объекты User — сосед не
должен получить возможность мутировать чужую модель напрямую, а форма
{id, username, email, full_name, is_active} — минимальный "brief"-профиль,
которого достаточно для чужих UI-списков (участник задачи, автор события и
т.п.), без полного профиля (аватар, роли, settings — см.
apps.users.services.profile_service.build_response, который остаётся
приватным для этой аппки).

full_name — это apps.users.services.options_service.full_name_for
("{first_name} {last_name}".strip(), с откатом на display_name, затем
username), вызывается отсюда напрямую, а не копируется. ЭТО НЕ то же самое,
что profile_service.build_response's fio: у fio другой порядок полей
("{last_name} {first_name} {patronymic}"), в нём участвует patronymic и
нет отката на display_name/username. Не путать одно с другим.

Запросы здесь сужены до колонок, которые реально нужны (.values(...)) —
это граница между аппками, и незачем поднимать в память password_hash и
settings из полной User-строки ради 5 полей брифа.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Iterable

from apps.core.services import require_service
from apps.users.models import User, UserStatus
from apps.users.services.options_service import full_name_for

_BRIEF_FIELDS = ("id", "username", "email", "first_name", "last_name",
                 "display_name", "status")


def _brief_from_values(row: dict) -> dict:
    # full_name_for only reads .first_name/.last_name/.display_name/.username —
    # a SimpleNamespace satisfies that without instantiating a real User row
    # (this module never hands out ORM objects, not even internally).
    stub = SimpleNamespace(first_name=row["first_name"], last_name=row["last_name"],
                          display_name=row["display_name"], username=row["username"])
    return {
        "id": row["id"],
        "username": row["username"],
        "email": row["email"],
        "full_name": full_name_for(stub),
        "is_active": row["status"] == UserStatus.ACTIVE,
    }


def get_user_brief(user_id: int) -> dict | None:
    """Minimal profile for a single user, or ``None`` if ``user_id`` doesn't
    resolve to any row (unknown/deleted user)."""
    require_service("users")
    row = User.objects.filter(pk=user_id).values(*_BRIEF_FIELDS).first()
    return _brief_from_values(row) if row is not None else None


def get_users_brief(user_ids: Iterable[int]) -> list[dict]:
    """Bulk variant of ``get_user_brief`` — one query for every id in
    ``user_ids``. Unknown ids are simply absent from the result (same
    "unknown -> not present" contract as ``get_user_brief``'s ``None``,
    just expressed as omission instead of a null entry since this returns
    a list)."""
    require_service("users")
    rows = User.objects.filter(pk__in=list(user_ids)).values(*_BRIEF_FIELDS)
    return [_brief_from_values(row) for row in rows]
