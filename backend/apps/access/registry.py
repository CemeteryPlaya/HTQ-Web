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


def _declared() -> list[tuple[str, str]]:
    """Пары ``(путь, название)`` из всех аппок, объявивших реестр."""
    found: list[tuple[str, str]] = []
    for config in django_apps.get_app_configs():
        if not module_has_submodule(config.module, _SUBMODULE):
            continue
        module = __import__(f"{config.name}.{_SUBMODULE}", fromlist=[_SUBMODULE])
        for row in getattr(module, "FUNCTIONS", ()):
            found.append((row[0], row[1]))
    return found


def kind_of(path: str) -> str:
    """Уровень узла по числу сегментов пути."""
    depth = path.count(".")
    if depth == 0:
        return MODULE
    if depth == 1:
        return FUNCTION
    return FIELD


def ancestors(path: str) -> list[str]:
    """Пути предков от ближайшего к корню: ``a.b.c`` → ``[a.b, a]``."""
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

    titles = _module_titles()
    known = {name: {"path": name, "title": titles.get(name, name), "kind": MODULE}
             for name in KNOWN_SERVICES}

    rows: dict[str, dict] = dict(known)
    for path, title in _declared():
        module = path.split(".")[0]
        if module not in known:
            # Функция, объявленная под несуществующим модулем, — опечатка в
            # аппке. Тихо принять её значило бы завести право, которое никогда
            # ни на что не влияет.
            raise ValueError(
                f"{_SUBMODULE}: путь {path!r} ссылается на модуль {module!r}, "
                f"которого нет в KNOWN_SERVICES"
            )
        rows[path] = {"path": path, "title": title, "kind": kind_of(path)}

    return [rows[path] for path in sorted(rows)]


def paths() -> set[str]:
    return {row["path"] for row in nodes()}


def is_known(path: str) -> bool:
    return path in paths()


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
