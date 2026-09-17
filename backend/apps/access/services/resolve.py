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

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

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


def _position_role_ids(
    user_id: int, company: str
) -> list[tuple[int, str, int | None]]:
    """Роли штатной должности пользователя, уже с готовой областью.

    До задачи 1b возвращала только ``role_id`` — область должностной роли
    была безусловной константой (``COMPANY``), считать её было нечего.
    Теперь у ``PositionRole`` есть ``scope_kind``, а ``DEPARTMENT``
    резолвится по ДЕРЖАТЕЛЮ (докстринг ``PositionRole.scope_kind``) — то есть
    нужен ``department_id`` из ТОЙ ЖЕ карточки ``brief``, которая здесь уже
    читается ради ``position_id``. Отдавать наружу только id и вычислять
    область вторым проходом значило бы либо второй запрос карточки, либо
    протаскивать ``brief`` как отдельный параметр в ``_role_scopes`` — оба
    варианта хуже, чем вернуть готовую тройку (id, kind, scope_id) один раз,
    здесь же, где карточка и так под рукой. Имя оставлено прежним — вызывающая
    сторона (``_role_scopes``) всё ещё про роли ЭТОЙ должности, просто с
    результатом разбора, а не голыми id.

    Пусто, если карточки нет: без неё неизвестен ни ``position_id``, ни
    отдел держателя, и назначать роли этой должности вслепую значило бы
    выдать их тому, у кого нет даже основания их получить.
    """
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

    department_id = brief.get("department_id")
    result: list[tuple[int, str, int | None]] = []
    for role_id, scope_kind in (
        PositionRole.objects
        .filter(company_slug=company, position_id=brief["position_id"])
        .values_list("role_id", "scope_kind")
    ):
        if scope_kind == ScopeKind.COMPANY:
            result.append((role_id, ScopeKind.COMPANY, None))
        elif scope_kind == ScopeKind.DEPARTMENT:
            if department_id is None:
                # Держатель без отдела — не должно случаться (``hr.Employee.
                # department`` обязательное поле), но резолвер прав не должен
                # доверять этому вслепую: честно ничего не выдаём этой роли,
                # а не молча подставляем COMPANY-призрак.
                continue
            result.append((role_id, ScopeKind.DEPARTMENT, department_id))
        else:
            # ScopeKind.SITE и любые будущие значения: сегодняшняя карточка
            # держателя не несёт site_id, посчитать «свой объект» нечем.
            # Пропускаем роль (fail closed), а не расширяем её до COMPANY —
            # ровно то расширение, ради устранения которого заведено поле.
            continue
    return result


def _role_scopes(
    user, company: str | None
) -> tuple[dict[int, tuple[str, int | None]], tuple[str, ...]]:
    """``role_id`` → область, с которой роль досталась пользователю, + источники.

    Область должностной роли задаёт ``PositionRole.scope_kind`` (задача 1b):
    ``COMPANY`` по умолчанию — область не сужается вовсе, ``DEPARTMENT`` —
    отдел ДЕРЖАТЕЛЯ, а не должности (докстринг модели). ``_position_role_ids``
    уже отдаёт готовую пару область/id — здесь она только раскладывается в
    карту по ``role_id``.

    Наследованные роли (``apps.access.services.inheritance`` — должность
    вышестоящей компании, помеченная обслуживающей) добавляются в карту ПОСЛЕ
    должностных ролей БЕЗУСЛОВНОЙ перезаписью (``scopes.update``, а не через
    ``_SCOPE_WIDTH``): наследование всегда даёт ``company`` — самую широкую из
    возможных областей (``inheritance.inherit`` — «сузить нельзя, у человека
    нет отдела в чужой компании»), — поэтому безусловная перезапись и есть
    «шире побеждает» даже тогда, когда должностная роль того же ``role_id``
    была ``DEPARTMENT``: более узкой области пережить объединение с самой
    широкой неоткуда.

    Личные назначения (``RoleAssignment``) идут ПОСЛЕДНИМИ и уже сравниваются
    через ``_SCOPE_WIDTH`` (сравнивает `` > ``, а не `` >= ``): более узкое
    назначение не переписывает то, что должность или наследование уже дали
    шире.

    Второй элемент — слаги предков, чья обслуживающая должность фактически
    дала хоть одну роль (``inheritance.Inherited.sources``, задача 6 блока C):
    один обход даёт и роли, и объяснение их происхождения — второй обход по
    дереву владения ради одного только списка слагов был бы тем самым лишним
    переключением схемы на страницу, которого ``Resolution`` целиком избегает.
    """
    if company is None:
        return {}, ()
    from apps.access.services import inheritance

    user_id, _ = identity(user)
    scopes: dict[int, tuple[str, int | None]] = {
        role_id: (kind, scope_id)
        for role_id, kind, scope_id in _position_role_ids(user_id, company)
    }
    inherited = inheritance.inherit(user_id, company)
    scopes.update(inherited.scopes)
    for row in RoleAssignment.objects.filter(company_slug=company, user_id=user_id):
        current = scopes.get(row.role_id)
        if current is None or _SCOPE_WIDTH[row.scope_kind] > _SCOPE_WIDTH[current[0]]:
            scopes[row.role_id] = (row.scope_kind, row.scope_id)
    return scopes, inherited.sources


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


@dataclass(frozen=True)
class Resolution:
    """Роли пользователя в компании и их явные узлы — один расчёт на запрос.

    Существует затем, что ``/me`` зовёт ``page_hidden`` по каждому узлу-странице
    (их 32) плюс ``permissions_for`` и ``depth_map``: без общего контекста один
    запрос стоил бы 35 пересчётов ролей (``_role_scopes`` — три запроса
    каждый), а после наследования по дереву владения
    (``apps.access.services.inheritance``, которое ``_role_scopes`` теперь
    зовёт) — ещё и 35 переключений схемы поверх этого. Один расчёт на запрос
    держит и переключения схемы в единственном числе, а не в размере списка
    страниц.

    Передаётся ЯВНО через параметр ``resolution=``, а не живёт в
    ``contextvar``: состояние, пережившее вызов, пришлось бы сбрасывать между
    запросами и между тестами, и ошибка в этом сбросе отдала бы права одного
    пользователя другому. Явный параметр живёт в кадре вызывающего и не может
    протечь никуда мимо него.

    ``frozen=True`` запрещает только переприсвоить ``scopes``/``rows``, а не
    поменять их содержимое — ``res.rows[42]["hr"] = ...`` для обычных ``dict``
    прошло бы молча. Поэтому обе карты (и вложенная карта узлов внутри
    ``rows``) оборачиваются в ``MappingProxyType`` в ``resolve_for`` — только
    это и делает гарантию неизменности настоящей, а не декларативной: попытка
    мутировать бросает ``TypeError`` вместо тихой порчи чужого запроса.

    ``inherited_from`` (задача 6 блока C) — слаги компаний-предков, чья
    обслуживающая должность фактически дала хоть одну роль в ``scopes``; уже
    ``tuple`` — неизменность не нужно достраивать ``MappingProxyType``, как для
    словарей выше. Приходит из того же обхода, что и наследованные роли
    (``inheritance.inherit`` внутри ``_role_scopes``), а не отдельным проходом
    по дереву владения: второй обход стоил бы ровно того переключения схемы на
    предка, которого весь этот класс существует, чтобы избежать.
    """

    scopes: Mapping[int, tuple[str, int | None]]
    rows: Mapping[int, Mapping[str, frozenset[str]]]
    inherited_from: tuple[str, ...]


def resolve_for(user, company: str | None) -> Resolution:
    """Посчитать роли пользователя в компании один раз для повторного использования.

    ⚠️ Ветка суперпользователя сюда НЕ входит: у него полный набор прав без
    единого запроса (см. каждую публичную функцию ниже), и построение
    ``Resolution`` для него означало бы вернуть в горячий путь ровно те
    запросы, которые эта функция должна убрать. Решать, нужен ли вообще
    контекст, — дело вызывающего (``identity(user)`` до вызова этой функции).

    Оборачивает обе карты в ``MappingProxyType`` (и ``rows`` — на обоих
    уровнях: сама карта ролей и карта узлов КАЖДОЙ роли) прежде чем положить
    их в ``Resolution``: объект — константа с момента постройки, и любой
    код, который захочет обогатить его данными (например, наследованием по
    дереву владения), обязан построить НОВЫЙ ``Resolution``, а не менять
    существующий на месте, — иначе он бы подмешал узлы одной роли другой или
    одного запроса другому. По этой же причине наследование
    (``apps.access.services.inheritance``) не трогает готовый ``Resolution``
    вовсе: оно работает раньше, внутри ``_role_scopes``, и участвует в самих
    входных данных, из которых ``Resolution`` строится один-единственный раз.
    """
    scopes, inherited_from = _role_scopes(user, company)
    rows = _rows_by_role(scopes)
    return Resolution(
        scopes=MappingProxyType(scopes),
        rows=MappingProxyType(
            {role_id: MappingProxyType(nodes) for role_id, nodes in rows.items()}
        ),
        inherited_from=inherited_from,
    )


# ── Публичные ответы ────────────────────────────────────────────────────────
#
# Каждая функция принимает необязательный ``resolution=`` — уже готовый
# ``Resolution`` для той же пары (user, company). Без него функция считает
# роли сама (``resolve_for``), как и раньше; так остаются рабочими все места,
# где параметр не нужен (одиночный вызов, а не 35 в цикле /me).
#
# Ветка суперпользователя в каждой функции стоит ПЕРВОЙ, перед обращением к
# ``resolution`` и до вызова ``resolve_for`` — у суперпользователя ответ не
# стоит ни одного запроса, и строить ему контекст значило бы вернуть в горячий
# путь ровно то, что параметр ``resolution`` должен убрать.


def flags_for(user, node: str, company: str | None, *,
              resolution: Resolution | None = None) -> frozenset[str]:
    """Действующая глубина пользователя на узле: объединение по всем ролям."""
    _user_id, is_superuser = identity(user)
    if is_superuser:
        return frozenset(depth.FLAGS)

    res = resolution or resolve_for(user, company)
    if not res.scopes:
        return frozenset()

    result: frozenset[str] = frozenset()
    for _role_id, nodes in res.rows.items():
        result |= _nearest(nodes, node)
    return result


def can(user, node: str, flag: str, company: str | None, *,
        resolution: Resolution | None = None) -> bool:
    return flag in flags_for(user, node, company, resolution=resolution)


def page_hidden(user, route: str, company: str | None, *,
                resolution: Resolution | None = None) -> bool:
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
    res = resolution or resolve_for(user, company)
    opinions = [nodes[node] for nodes in res.rows.values() if node in nodes]
    if not opinions:
        return False
    return not any(opinions)


def depth_map(user, company: str | None, *,
              resolution: Resolution | None = None) -> dict[str, list[str]]:
    """Все узлы, на которых у пользователя есть хоть что-то, → список флагов.

    Узлы без единого флага в карту не попадают — по той же причине, по которой
    модули со ``none`` не попадают в ``permissions_for``: отсутствие ключа и
    есть «нет доступа», а явный пустой список заставлял бы обе стороны
    различать два способа сказать одно и то же.
    """
    _user_id, is_superuser = identity(user)
    if is_superuser:
        return {name: list(depth.FLAGS) for name in _known_modules()}

    res = resolution or resolve_for(user, company)
    if not res.scopes:
        return {}

    merged: dict[str, frozenset[str]] = {}
    for _role_id, nodes in res.rows.items():
        for path, flags in nodes.items():
            merged[path] = merged.get(path, frozenset()) | flags
    return {path: sorted(flags) for path, flags in merged.items() if flags}


def permissions_for(user, company: str | None, *,
                    resolution: Resolution | None = None) -> dict[str, dict]:
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

    res = resolution or resolve_for(user, company)
    if not res.scopes:
        return {}

    by_role = res.rows
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
            kind, scope_id = res.scopes[role_id]
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


def permission_level(user, module: str, company: str | None, *,
                     resolution: Resolution | None = None) -> str:
    entry = permissions_for(user, company, resolution=resolution).get(module)
    return entry["level"] if entry else Level.NONE
