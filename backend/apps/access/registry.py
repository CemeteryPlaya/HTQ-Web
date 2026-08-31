"""Реестр функций платформы — то, на что назначается глубина.

Три уровня, разделённые точкой:

    hr                      модуль   — домен целиком
    hr.employees            функция  — экран или операция внутри домена
    hr.employees.salary     поле     — отдельный столбец или блок данных

**Глубина наследуется вниз.** Роли задают её на том уровне, на котором она
осмысленна: обычно на модуле, точечно — на функции, и совсем редко на поле
(зарплата, паспорт). Не заданное явно берётся с ближайшего предка, поэтому
роль остаётся набором из десятка строк, а не тысячи. Требовать явного решения
по каждому столбцу значило бы получить матрицу, которую никто не заполнит
целиком — и та её часть, до которой не дошли руки, была бы неотличима от
осознанного «нет доступа».

**Функции принадлежат аппкам, а не этому файлу.** Каждая аппка кладёт
``apps/<домен>/access_functions.py`` с кортежем ``FUNCTIONS`` и описывает СВОИ
экраны. Соглашение то же, что у ``metrics.py`` и ``holding.py``: реестр их
только находит. Иначе этот модуль импортировал бы чужие потроха, а список
разъезжался бы с доменом при каждой правке.
"""

from __future__ import annotations

from django.apps import apps as django_apps
from django.utils.module_loading import module_has_submodule

MODULE = "module"
FUNCTION = "function"
FIELD = "field"
PAGE = "page"

#: Префикс узла-страницы. Страницы намеренно НЕ входят в точечное дерево
#: модулей: страница может собирать данные нескольких доменов, и подчинять её
#: одному из них значило бы соврать о том, что она такое.
PAGE_PREFIX = "page:"

#: Имя модуля, объявляемого аппкой. Совпадает с именем сервиса в
#: ``apps.core.models.KNOWN_SERVICES`` — второй список модулей платформа не
#: заводит (то же решение, что в §3 спеки стадии 2).
_SUBMODULE = "access_functions"


def _module_titles() -> dict[str, str]:
    """Человеческие названия модулей — из ``verbose_name`` их AppConfig."""
    titles: dict[str, str] = {}
    for config in django_apps.get_app_configs():
        if not config.name.startswith("apps."):
            continue
        titles[config.label] = str(config.verbose_name)
    return titles


FUNCTIONAL = "functional"
DOCUMENT = "document"


def _module_kinds() -> dict[str, str]:
    """Тип каждого модуля: инструмент или картотека.

    Аппка объявляет его константой ``MODULE_KIND`` в ``access_functions.py``.
    Умолчание — ``document``: подавляющее большинство доменов именно картотеки,
    и требовать объявления от каждого значило бы завести обязательный ритуал
    ради меньшинства.
    """
    kinds: dict[str, str] = {}
    for config in django_apps.get_app_configs():
        if not module_has_submodule(config.module, _SUBMODULE):
            continue
        module = __import__(f"{config.name}.{_SUBMODULE}", fromlist=[_SUBMODULE])
        kind = getattr(module, "MODULE_KIND", DOCUMENT)
        if kind not in (FUNCTIONAL, DOCUMENT):
            raise ValueError(
                f"{config.name}.{_SUBMODULE}: MODULE_KIND={kind!r}; "
                f"допустимы {FUNCTIONAL!r} и {DOCUMENT!r}"
            )
        for row in getattr(module, "FUNCTIONS", ()):
            kinds[row[0].split(".")[0]] = kind
    return kinds


def _declared() -> list[tuple[str, str, tuple[str, ...]]]:
    """``(путь, название, применимые признаки)`` из всех аппок.

    Третий элемент необязателен: без него к узлу применимы все четыре признака.
    """
    from apps.access import depth

    found: list[tuple[str, str, tuple[str, ...]]] = []
    for config in django_apps.get_app_configs():
        if not module_has_submodule(config.module, _SUBMODULE):
            continue
        module = __import__(f"{config.name}.{_SUBMODULE}", fromlist=[_SUBMODULE])
        for row in getattr(module, "FUNCTIONS", ()):
            flags = tuple(row[2]) if len(row) > 2 else depth.FLAGS
            unknown = sorted(set(flags) - set(depth.FLAGS))
            if unknown:
                raise ValueError(
                    f"{_SUBMODULE}: узел {row[0]!r} объявил несуществующие "
                    f"признаки глубины: {unknown}"
                )
            found.append((row[0], row[1], flags))
    return found


def kind_of(path: str) -> str:
    """Уровень узла по числу сегментов пути."""
    if path.startswith(PAGE_PREFIX):
        return PAGE
    depth = path.count(".")
    if depth == 0:
        return MODULE
    if depth == 1:
        return FUNCTION
    return FIELD


def ancestors(path: str) -> list[str]:
    """Пути предков от ближайшего к корню: ``a.b.c`` → ``[a.b, a]``.

    У страницы предков нет: она плоская и ничего не наследует.
    """
    if path.startswith(PAGE_PREFIX):
        return []
    parts = path.split(".")
    return [".".join(parts[:i]) for i in range(len(parts) - 1, 0, -1)]


def self_and_ancestors(path: str) -> list[str]:
    """Сам узел, затем предки — порядок поиска ближайшего явного права."""
    return [path, *ancestors(path)]


def nodes() -> list[dict]:
    """Плоский список узлов реестра: модули, их функции и поля.

    Модули берутся из ``KNOWN_SERVICES``, а не из объявлений аппок: домен
    существует в реестре прав, даже если ещё не расписал свои экраны, — иначе
    роль нельзя было бы выдать на него целиком.
    """
    from apps.core.models import KNOWN_SERVICES

    from apps.access import depth

    titles = _module_titles()
    kinds = _module_kinds()
    known = {name: {"path": name, "title": titles.get(name, name), "kind": MODULE,
                    "module_kind": kinds.get(name, DOCUMENT),
                    "flags": list(depth.FLAGS)}
             for name in KNOWN_SERVICES}

    rows: dict[str, dict] = dict(known)
    for path, title, flags in _declared():
        module = path.split(".")[0]
        if module not in known:
            # Функция, объявленная под несуществующим модулем, — опечатка в
            # аппке. Тихо принять её значило бы завести право, которое никогда
            # ни на что не влияет.
            raise ValueError(
                f"{_SUBMODULE}: путь {path!r} ссылается на модуль {module!r}, "
                f"которого нет в KNOWN_SERVICES"
            )
        rows[path] = {"path": path, "title": title, "kind": kind_of(path),
                      "module_kind": kinds.get(module, DOCUMENT),
                      "flags": list(flags)}

    for row in rows.values():
        row["presets"] = _presets_for(row)
    return [rows[path] for path in sorted(rows)] + page_nodes()


def page_nodes() -> list[dict]:
    """Узлы-страницы: только «видно» и «не видно»."""
    from apps.access.pages import PAGES

    return [
        {"path": f"{PAGE_PREFIX}{route}", "title": title, "kind": PAGE,
         "module_kind": DOCUMENT, "flags": ["view"], "presets": ["none", "view"],
         "route": route}
        for route, title in PAGES
    ]


def _presets_for(row: dict) -> list[str]:
    """Уровни, которые вообще осмысленно предлагать для узла.

    У МОДУЛЯ их набор определяется его типом: у инструмента (мессенджер,
    конференции) — три («нет доступа», «пользователь», «администратор»), у
    картотеки — шесть из постановки. Именно здесь чинится то, что заметил
    заказчик: функции таких модулей уже отвечали правильно, а сам модуль
    по-прежнему предлагал CRUD.

    У ФУНКЦИИ и ПОЛЯ набор считается из применимых признаков: предлагается
    ровно тот уровень, все признаки которого узлу применимы.
    """
    from apps.access import depth

    if row["kind"] == MODULE:
        return list(depth.FUNCTIONAL_PRESETS if row["module_kind"] == FUNCTIONAL
                    else depth.DOCUMENT_PRESETS)

    applicable = set(row["flags"])
    return [name for name in depth.DOCUMENT_PRESETS
            if depth.PRESETS[name] <= applicable]


def paths() -> set[str]:
    return {row["path"] for row in nodes()}


def is_known(path: str) -> bool:
    return path in paths()


def presets_for(path: str) -> list[str]:
    """Уровни, допустимые для узла. Пустой список — узла нет в реестре."""
    for row in nodes():
        if row["path"] == path:
            return row["presets"]
    return []


def applicable_flags(path: str) -> frozenset[str]:
    """Признаки глубины, осмысленные для узла.

    Не всякая функция описывается CRUD'ом. «Войти в конференцию» и «написать
    сообщение» — действия: у них есть только «доступно» и «нет доступа», а
    «удалять» там не значит ничего. Раньше редактор позволял задать такую
    бессмыслицу, и понять, что она означает, не мог никто, — теперь она
    невыразима.
    """
    for row in nodes():
        if row["path"] == path:
            return frozenset(row["flags"])
    return frozenset()


def is_action(path: str) -> bool:
    """Узел-действие: единственный осмысленный признак — «доступно»."""
    from apps.access import depth

    return applicable_flags(path) == frozenset({depth.VIEW})


def tree() -> list[dict]:
    """Реестр деревом — форма для матрицы прав в интерфейсе."""
    flat = {row["path"]: {**row, "children": []} for row in nodes()}
    roots: list[dict] = []
    for path in sorted(flat):
        parent = ".".join(path.split(".")[:-1])
        if parent and parent in flat:
            flat[parent]["children"].append(flat[path])
        else:
            roots.append(flat[path])
    return roots
