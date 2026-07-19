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

full_name собирается тем же способом, что и в
apps.users.services.options_service.full_name_for /
apps.users.services.profile_service.build_response's fio: "{first_name}
{last_name}".strip(), с откатом на display_name, затем username.
"""
from __future__ import annotations

from typing import Iterable

from apps.core.services import require_service
from apps.users.models import User


def _full_name(user: User) -> str:
    """Same fallback chain as options_service.full_name_for — reused
    logic, not reinvented, kept private to this module since it only
    operates on already-fetched User rows (not a queryset)."""
    name = f"{user.first_name} {user.last_name}".strip()
    return name or user.display_name or user.username


def _brief(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "full_name": _full_name(user),
        "is_active": user.is_active,
    }


def get_user_brief(user_id: int) -> dict | None:
    """Minimal profile for a single user, or ``None`` if ``user_id`` doesn't
    resolve to any row (unknown/deleted user)."""
    require_service("users")
    user = User.objects.filter(pk=user_id).first()
    return _brief(user) if user is not None else None


def get_users_brief(user_ids: Iterable[int]) -> list[dict]:
    """Bulk variant of ``get_user_brief`` — one query for every id in
    ``user_ids``. Unknown ids are simply absent from the result (same
    "unknown -> not present" contract as ``get_user_brief``'s ``None``,
    just expressed as omission instead of a null entry since this returns
    a list)."""
    require_service("users")
    users = User.objects.filter(pk__in=list(user_ids))
    return [_brief(user) for user in users]
