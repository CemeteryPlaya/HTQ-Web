"""Разрешение прав — спека стадии 2, §1.5 и §1.8.

Порядок ветвления зафиксирован спекой и повторён здесь дословно: это
единственное место платформы, где «нет ответа» и «нет прав» обязаны совпадать.
Любая подстановка по умолчанию тихо расширяет доступ, поэтому ветки «нет
компании» и «нет ролей» возвращают пусто, а не что-нибудь разумное.

Глубина задаётся на узлах реестра функций и **наследуется вниз**: у узла без
собственной строки действует глубина ближайшего предка, у которого она есть.
Роль поэтому остаётся набором из десятка строк, а не тысячи.

Прежние уровни (модуль × none/read/write/admin) остались в ОТВЕТАХ — на них
держатся маршруты фронта и гейт ``api_view`` — но перестали быть источником
истины: теперь это проекция глубины, и считается она здесь.
"""

from __future__ import annotations

from apps.access import depth, registry
from apps.access.models import (
    LEVEL_ORDER,
    Level,
    PositionRole,
    RoleAssignment,
    RolePermission,
    ScopeKind,
)
from apps.access.services.identity import identity
from htqweb.fallback import fallback

# Чем шире область, тем больше число — сравнивается так же, как уровни.
_SCOPE_WIDTH = {ScopeKind.SITE: 0, ScopeKind.DEPARTMENT: 1, ScopeKind.COMPANY: 2}


def _known_modules() -> list[str]:
    from apps.core.models import KNOWN_SERVICES

    return list(KNOWN_SERVICES)


def _position_role_ids(user_id: int, company: str) -> list[int]:
    """Роли штатной должности пользователя. Пусто, если карточки нет."""
    try:
        from apps.hr import interface as hr

        brief = hr.get_employee_brief(user_id)
    except Exception as exc:
        # Кадровый модуль выключен или недоступен: должностные роли не
        # прочитать. Это ПОДМЕНА — права считаются по неполным данным, — и она
        # обязана быть видна. Иначе выключенный hr незаметно снимет доступ у
        # всей компании, а причину будут искать в правах.
        fallback("access.resolve.hr_unavailable", None,
                 reason="кадровый модуль недоступен, роли должности не учтены",
                 exc=exc, expected=True, user_id=user_id, company=company)
        return []
    if brief is None or brief.get("position_id") is None:
        return []
    return list(
        PositionRole.objects
        .filter(company_slug=company, position_id=brief["position_id"])
        .values_list("role_id", flat=True)
    )


def _role_scopes(user, company: str | None) -> dict[int, tuple[str, int | None]]:
    """``role_id`` → область, с которой роль досталась пользователю.

    Должностная роль действует на всю компанию: область сужается только личным
    назначением.
    """
    if company is None:
        return {}
    user_id, _ = identity(user)
    scopes: dict[int, tuple[str, int | None]] = {
        role_id: (ScopeKind.COMPANY, None)
        for role_id in _position_role_ids(user_id, company)
    }
    for row in RoleAssignment.objects.filter(company_slug=company, user_id=user_id):
        current = scopes.get(row.role_id)
        if current is None or _SCOPE_WIDTH[row.scope_kind] > _SCOPE_WIDTH[current[0]]:
            scopes[row.role_id] = (row.scope_kind, row.scope_id)
    return scopes


def _rows_by_role(role_ids) -> dict[int, dict[str, frozenset[str]]]:
    """Явно заданные узлы каждой роли. Наследование считается поверх них."""
    by_role: dict[int, dict[str, frozenset[str]]] = {rid: {} for rid in role_ids}
    for row in RolePermission.objects.filter(role_id__in=list(role_ids)):
        by_role.setdefault(row.role_id, {})[row.node] = row.flags
    return by_role


def _nearest(nodes: dict[str, frozenset[str]], path: str) -> frozenset[str]:
    """Глубина ближайшего предка, у которого она задана явно.

    Пустой набор у найденного предка — это ЗАПРЕТ, а не «ищи выше»: им
    перекрывают разрешение, выданное на модуль целиком.
    """
    for candidate in registry.self_and_ancestors(path):
        if candidate in nodes:
            return nodes[candidate]
    return frozenset()


# ── Публичные ответы ────────────────────────────────────────────────────────


def flags_for(user, node: str, company: str | None) -> frozenset[str]:
    """Действующая глубина пользователя на узле: объединение по всем ролям."""
    _user_id, is_superuser = identity(user)
    if is_superuser:
        return frozenset(depth.FLAGS)

    scopes = _role_scopes(user, company)
    if not scopes:
        return frozenset()

    result: frozenset[str] = frozenset()
    for _role_id, nodes in _rows_by_role(scopes).items():
        result |= _nearest(nodes, node)
    return result


def can(user, node: str, flag: str, company: str | None) -> bool:
    return flag in flags_for(user, node, company)


def page_hidden(user, route: str, company: str | None) -> bool:
    """Закрыта ли страница явным запретом.

    Страница — ВЕТО, а не разрешение: отсутствие строки означает «нет особого
    мнения», и маршрут работает по обычным правилам. Считать незаданную
    страницу закрытой значило бы сделать бесполезной всякую роль без полного
    перечня страниц, а перечень пришлось бы обновлять при каждом новом экране.

    Запрет действует, только если НИ ОДНА роль пользователя не разрешила
    страницу явно: роли складываются объединением, и запрет в одной не отменяет
    разрешения в другой (то же правило, что для глубины).
    """
    _user_id, is_superuser = identity(user)
    if is_superuser:
        return False

    node = f"{registry.PAGE_PREFIX}{route}"
    scopes = _role_scopes(user, company)
    opinions = [nodes[node] for nodes in _rows_by_role(scopes).values() if node in nodes]
    if not opinions:
        return False
    return not any(opinions)


def depth_map(user, company: str | None) -> dict[str, list[str]]:
    """Все узлы, на которых у пользователя есть хоть что-то, → список флагов.

    Узлы без единого флага в карту не попадают — по той же причине, по которой
    модули со ``none`` не попадают в ``permissions_for``: отсутствие ключа и
    есть «нет доступа», а явный пустой список заставлял бы обе стороны
    различать два способа сказать одно и то же.
    """
    _user_id, is_superuser = identity(user)
    if is_superuser:
        return {name: list(depth.FLAGS) for name in _known_modules()}

    scopes = _role_scopes(user, company)
    if not scopes:
        return {}

    merged: dict[str, frozenset[str]] = {}
    for _role_id, nodes in _rows_by_role(scopes).items():
        for path, flags in nodes.items():
            merged[path] = merged.get(path, frozenset()) | flags
    return {path: sorted(flags) for path, flags in merged.items() if flags}


def permissions_for(user, company: str | None) -> dict[str, dict]:
    """Карта «модуль → уровень и область» — проекция глубины (§4.5).

    Уровень модуля считается по ВСЕМУ его поддереву, а не по одному узлу
    модуля: роль, выдавшая права только на ``hr.employees``, обязана открывать
    маршруты модуля ``hr`` — иначе человек с доступом к экрану не смог бы на
    него попасть.
    """
    _user_id, is_superuser = identity(user)
    if is_superuser:
        return {
            module: {"level": Level.ADMIN,
                     "scope": {"kind": ScopeKind.COMPANY, "id": None}}
            for module in _known_modules()
        }
    if company is None:
        return {}

    scopes = _role_scopes(user, company)
    if not scopes:
        return {}

    by_role = _rows_by_role(scopes)
    result: dict[str, dict] = {}
    for module in _known_modules():
        for role_id, nodes in by_role.items():
            subtree: frozenset[str] = frozenset()
            for path, flags in nodes.items():
                if path == module or path.startswith(f"{module}."):
                    subtree |= flags
            level = depth.legacy_level(subtree)
            if level == Level.NONE:
                continue
            kind, scope_id = scopes[role_id]
            best = result.get(module)
            if best is None or LEVEL_ORDER[level] > LEVEL_ORDER[best["level"]]:
                result[module] = {"level": level,
                                  "scope": {"kind": kind, "id": scope_id}}
            elif (LEVEL_ORDER[level] == LEVEL_ORDER[best["level"]]
                  and _SCOPE_WIDTH[kind] > _SCOPE_WIDTH[best["scope"]["kind"]]):
                # Область расширяется только правом ТОГО ЖЕ уровня: широкое
                # чтение не должно расширять узкое администрирование.
                best["scope"] = {"kind": kind, "id": scope_id}
    return result


def permission_level(user, module: str, company: str | None) -> str:
    entry = permissions_for(user, company).get(module)
    return entry["level"] if entry else Level.NONE
