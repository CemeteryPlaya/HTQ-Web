"""Кто правит справочники: роль с правом правки И поддомен управляющей компании.

Справочники общие для группы (D-03), поэтому правка из дочерней компании
запрещена даже держателю роли: иначе бухгалтер дочерней компании поменял
бы ставку НДС всем. Управляющая компания — компания вида «холдинг» (Q-E03).
"""

from __future__ import annotations

from apps.access import interface as access
from apps.companies import interface as companies


def can_edit(user, company_slug: str | None, node: str = "refdata", *,
             flags: tuple[str, ...] = ("edit", "create")) -> bool:
    """``flags`` — какие признаки глубины считаются правом правки. Календарь
    (узел ``refdata.production_calendar``) просит строго ``("edit",)``."""
    if getattr(user, "is_superuser", False):
        return True
    if not company_slug or not companies.is_holding(company_slug):
        return False
    have = access.flags_for(user, node, company_slug)
    return any(flag in have for flag in flags)
