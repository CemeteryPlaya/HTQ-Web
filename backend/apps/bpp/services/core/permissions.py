"""Проверки прав модуля тоньше уровня модуля — по узлу реестра.

Роли считаются один раз на запрос: гейт ``api_view(module=…)`` кладёт расчёт
в ``request.access_resolution``, здесь он переиспользуется, если совпадают
компания и пользователь (тот же приём, что ``apps/hr/rbac.py::NodeAccess``).
Принадлежность («свой документ», «участник проекта») проверяет документ,
не эта функция.
"""

from __future__ import annotations

from apps.access import interface as access
from apps.refdata import interface as refdata


def _company(request) -> str | None:
    return (getattr(request, "company", None) or {}).get("slug")


def _resolution(request, company):
    cached = getattr(request, "access_resolution", None)
    if cached and cached[0] == company and cached[1] == request.token.user_id:
        return cached[2]
    return None


def flags(request, node: str) -> frozenset[str]:
    company = _company(request)
    return access.flags_for(request.token, node, company,
                            resolution=_resolution(request, company))


def can(request, node: str, flag: str) -> bool:
    return flag in flags(request, node)


def article_groups_for(request) -> list[str]:
    """Коды групп статей, открытых пользователю (BR-010)."""
    return [group["code"] for group in refdata.article_groups()
            if group["is_active"] and can(request, group["node_key"], "view")]
