"""Разрешение прав — спека стадии 2, §1.5.

Порядок ветвления зафиксирован спекой и повторён здесь дословно: это
единственное место платформы, где «нет ответа» и «нет прав» обязаны совпадать.
Любая подстановка по умолчанию тихо расширяет доступ, поэтому ветки «нет
компании» и «нет ролей» возвращают пусто, а не что-нибудь разумное.
"""

from __future__ import annotations

from apps.access.models import (
    LEVEL_ORDER,
    Level,
    PositionRole,
    RoleAssignment,
    RoleModulePermission,
    ScopeKind,
)
from htqweb.fallback import fallback

# Чем шире область, тем больше число — сравнивается так же, как уровни.
_SCOPE_WIDTH = {ScopeKind.SITE: 0, ScopeKind.DEPARTMENT: 1, ScopeKind.COMPANY: 2}


def _known_modules() -> list[str]:
    from apps.core.models import KNOWN_SERVICES

    return list(KNOWN_SERVICES)


def _position_role_ids(user, company: str) -> list[int]:
    """Роли штатной должности пользователя. Пусто, если карточки нет."""
    try:
        from apps.hr import interface as hr

        brief = hr.get_employee_brief(user.id)
    except Exception as exc:
        # Кадровый модуль выключен или недоступен: должностные роли не
        # прочитать. Это ПОДМЕНА — права считаются по неполным данным, — и она
        # обязана быть видна. Иначе выключенный hr незаметно снимет доступ у
        # всей компании, а причину будут искать в правах.
        fallback("access.resolve.hr_unavailable", None,
                 reason="кадровый модуль недоступен, роли должности не учтены",
                 exc=exc, expected=True, user_id=user.id, company=company)
        return []
    if brief is None or brief.get("position_id") is None:
        return []
    return list(
        PositionRole.objects
        .filter(company_slug=company, position_id=brief["position_id"])
        .values_list("role_id", flat=True)
    )


def permissions_for(user, company: str | None) -> dict[str, dict]:
    """Карта «модуль → уровень и область». Модули со ``none`` не включаются."""
    if getattr(user, "is_superuser", False):
        return {
            module: {"level": Level.ADMIN,
                     "scope": {"kind": ScopeKind.COMPANY, "id": None}}
            for module in _known_modules()
        }
    if company is None:
        return {}

    # role_id -> область, с которой роль пришла. Должностная роль действует на
    # всю компанию: область сужается только личным назначением.
    scopes: dict[int, tuple[str, int | None]] = {
        role_id: (ScopeKind.COMPANY, None)
        for role_id in _position_role_ids(user, company)
    }
    for row in RoleAssignment.objects.filter(company_slug=company, user_id=user.id):
        current = scopes.get(row.role_id)
        if current is None or _SCOPE_WIDTH[row.scope_kind] > _SCOPE_WIDTH[current[0]]:
            scopes[row.role_id] = (row.scope_kind, row.scope_id)
    if not scopes:
        return {}

    result: dict[str, dict] = {}
    rows = (RoleModulePermission.objects
            .filter(role_id__in=list(scopes))
            .values("role_id", "module", "level"))
    for row in rows:
        if row["level"] == Level.NONE:
            continue
        kind, scope_id = scopes[row["role_id"]]
        best = result.get(row["module"])
        if best is None or LEVEL_ORDER[row["level"]] > LEVEL_ORDER[best["level"]]:
            result[row["module"]] = {"level": row["level"],
                                     "scope": {"kind": kind, "id": scope_id}}
        elif (LEVEL_ORDER[row["level"]] == LEVEL_ORDER[best["level"]]
              and _SCOPE_WIDTH[kind] > _SCOPE_WIDTH[best["scope"]["kind"]]):
            # Область расширяется только назначением ТОГО ЖЕ уровня: широкое
            # чтение не должно расширять узкое администрирование.
            best["scope"] = {"kind": kind, "id": scope_id}
    return result


def permission_level(user, module: str, company: str | None) -> str:
    entry = permissions_for(user, company).get(module)
    return entry["level"] if entry else Level.NONE
