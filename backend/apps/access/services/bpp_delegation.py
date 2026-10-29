"""Права на БЗО компании, чьё БЗО ведётся в другой компании (решение 19.10).

Запросы БЗО такой компании работают в схеме компании данных
(``htqweb/tenancy/bpp_delegation.py``), и права на них считаются там же:
гейт модуля и сервисы БЗО спрашивают компанию контекста. ``GET me`` на
поддомене самой компании обязан показывать то же самое, иначе меню и кнопки
раздела разошлись бы с тем, что пропустит сервер. Поэтому уровни модулей БЗО
и их узлы в ответе ``me`` берутся из компании данных, а всё остальное — из
своей.
"""

from __future__ import annotations

#: Модули, чьи данные живут в компании данных: сам БЗО и «Проекты».
DELEGATED_MODULES = ("bpp", "project")

#: Узлы делегируемых модулей, которые проверяет НЕ БЗО: «Доска задач проекта»
#: открывает доски задач, а задачи компании живут у неё самой
#: (``tasks/services/board_scope.py`` спрашивает узел в своей компании).
OWN_NODES = ("project.board",)


def _under(path: str, roots) -> bool:
    return any(path == root or path.startswith(f"{root}.") for root in roots)


def _delegated(path: str) -> bool:
    return _under(path, DELEGATED_MODULES) and not _under(path, OWN_NODES)


def merge_me(token, company: str | None, permissions: dict,
             depth_map: dict, *, resolution=None) -> tuple[dict, dict]:
    """``permissions``/``depth_map`` ответа ``me`` с правами на БЗО из компании
    данных. Компания ведёт БЗО у себя или пришёл суперпользователь (ему открыто
    всё и так) — ответ не меняется.

    ``resolution`` — уже посчитанные роли в своей компании (``MeView``):
    по ним — узлы ``OWN_NODES``. Их значение пишется в карту ЯВНО, даже
    пустым: фронт ищет узел, затем предков (``resolve.depth_map``), а предок
    ``project`` теперь пришёл из компании данных — без явной строки доска
    унаследовала бы чужое право."""
    from apps.access.services import resolve
    from apps.companies import interface as companies
    from htqweb.tenancy.db import use_company

    if company is None or getattr(token, "is_superuser", False):
        return permissions, depth_map
    host = companies.bpp_data_company(company)
    if host is None:
        return permissions, depth_map
    # Кадровую карточку (роли должности) резолвер читает в ТЕКУЩЕЙ схеме —
    # поэтому считаем внутри схемы компании данных.
    with use_company(host):
        host_resolution = resolve.resolve_for(token, host)
        host_permissions = resolve.permissions_for(token, host, resolution=host_resolution)
        host_depth = resolve.depth_map(token, host, resolution=host_resolution)
    merged_permissions = {module: entry for module, entry in permissions.items()
                          if module not in DELEGATED_MODULES}
    merged_permissions.update({module: entry for module, entry in host_permissions.items()
                               if module in DELEGATED_MODULES})
    merged_depth = {node: flags for node, flags in depth_map.items() if not _delegated(node)}
    merged_depth.update({node: flags for node, flags in host_depth.items() if _delegated(node)})
    for node in OWN_NODES:
        merged_depth[node] = sorted(resolve.flags_for(token, node, company,
                                                      resolution=resolution))
    return merged_permissions, merged_depth
