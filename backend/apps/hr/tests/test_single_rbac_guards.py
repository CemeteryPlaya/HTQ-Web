"""Блок I, задача 9: параллельная модель прав кадров снята — сторожа.

До этой задачи кадровый домен жил на ДВУХ моделях прав разом: модульный
гейт ``api_view(module="hr", level=…)`` над ролями ``apps.access`` (задачи
4–6) и старая ``apps.hr.access`` (``resolve_hr_access`` — уровень по
названию должности либо по ``Position.permissions``), которую вьюхи звали в
теле. Обе двери стояли «И-И». Задача 9 снимает вторую; эти тесты держат её
снятой — грепом по рабочему коду ``backend/apps/hr/**``, а не импортом
(импорт увидел бы только то, что модуль экспортирует, а не то, кто его
зовёт). Область — ``apps/hr``: только эта аппка вправе трогать
``Position`` напрямую (``apps/core/tests/test_app_isolation.py``), соседи
ходят через ``apps.hr.interface``, то есть читатель или писатель колонки
за пределами ``apps/hr`` невозможен по построению.

Что сторожится и КОГО исключает поимённо (каждое исключение — решение
контроллера, зафиксированное в ``task-9-brief.md``/``progress.md``):

1. ``classify_hr_level`` — эвристика по названию должности — не ВЫЗЫВАЕТСЯ
   нигде, кроме команды переноса (``apps.hr.interface.
   list_positions_hr_levels`` → ``manage.py access_backfill_positions``):
   перенос уровней в роли — единственное законное применение угадывания
   (Ruling C). Её помощник ``_level_from_permissions`` — там же плюс
   внутри самой эвристики.
2. ``Position.permissions`` никто не ЧИТАЕТ — колонка остаётся, но мертва
   (решение заказчика 3). Два исключения: ``apps.hr.interface.
   user_has_permission`` — контракт с ``apps.contracts`` до их перехода на
   узлы ``access`` (roadmap §6; Ruling A) — и сериализатор должности
   ``position_service.serialize`` — ``PositionOut.permissions`` остаётся в
   API, потому что через него в колонку попадают ключи contracts (Ruling
   B). Третье — сама эвристика переноса (``apps/hr/access.py``, читает
   только ``hr_level``).
3. ``Position.permissions`` никто не ПИШЕТ — сиды, ``participant_service``,
   ``group_structures`` перестали. Единственный оставшийся путь записи —
   API должностей (``PositionIn.permissions`` → ``position_service``, Ruling
   B): он не называет колонку по имени (``model_dump()``), сторожу не виден
   и намеренно не ловится.
4. Ручка ``employees/hr-level`` удалена (единственный потребитель снят
   задачей 8; отдавать её из ролей значило бы второй источник правды рядом
   с ``/api/access/v1/me``) — 404 по обоим написаниям пути.

Разбор — токенами (``tokenize``), а не подстрокой: файлы домена в изобилии
УПОМИНАЮТ старые имена в докстрингах и комментариях, объясняя, чем ручка
отличалась раньше, — проза сторожа не интересует, только код.
"""

from __future__ import annotations

import pathlib
import tokenize

import pytest
from django.test import Client

from apps.hr.tests.test_employees_api import _user_auth

BACKEND = pathlib.Path(__file__).resolve().parents[3]
HR = BACKEND / "apps" / "hr"

#: Кому можно ЗВАТЬ эвристику переноса (определения ``def …`` не в счёт).
HEURISTIC_CALLERS_ALLOWED: dict[str, frozenset[str]] = {
    # list_positions_hr_levels — источник для access_backfill_positions.
    "interface.py": frozenset({"classify_hr_level", "_level_from_permissions"}),
    # сама эвристика зовёт свой помощник (явный hr_level приоритетнее названия).
    "access.py": frozenset({"_level_from_permissions"}),
}

#: Читатели колонки ``Position.permissions`` (см. докстринг модуля, п. 2).
COLUMN_READERS_ALLOWED = frozenset({
    "interface.py",                  # user_has_permission — контракт с contracts (Ruling A)
    "services/position_service.py",  # serialize → PositionOut.permissions (Ruling B)
    "access.py",                     # _level_from_permissions — только hr_level, только для переноса
})

#: Кто вправе называть форму колонки (``"hr_level"``) — те же три: они
#: читают/сериализуют её, а не пишут.
COLUMN_SHAPE_ALLOWED = COLUMN_READERS_ALLOWED

_HEURISTIC_NAMES = frozenset({"classify_hr_level", "_level_from_permissions"})
_PERMISSIONS_STRINGS = frozenset({'"permissions"', "'permissions'"})
_HR_LEVEL_STRINGS = frozenset({'"hr_level"', "'hr_level'"})
_QUERYSET_PROJECTIONS = frozenset({"values", "values_list", "only", "defer"})
_SKIPPED = frozenset({
    tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE, tokenize.INDENT,
    tokenize.DEDENT, tokenize.ENCODING, tokenize.ENDMARKER,
})


def _working_code_files():
    """Рабочий код аппки: без тестов, миграций и кэшей."""
    for path in sorted(HR.rglob("*.py")):
        parts = path.relative_to(HR).parts
        if {"tests", "migrations", "__pycache__"} & set(parts):
            continue
        yield path


def _rel(path: pathlib.Path) -> str:
    return path.relative_to(HR).as_posix()


def _code_tokens(path: pathlib.Path) -> list[tokenize.TokenInfo]:
    """Токены кода: комментарии и служебные токены выброшены.

    Докстринги остаются STRING-токенами — сторожа ниже смотрят на NAME/OP
    и на СТРОКОВЫЕ ЛИТЕРАЛЫ ровно определённого вида (``"hr_level"``,
    ``"permissions"``), которые в докстринг целиком не влезают.
    """
    with tokenize.open(path) as fh:
        return [tok for tok in tokenize.generate_tokens(fh.readline)
                if tok.type not in _SKIPPED]


def _is_import_line(tok: tokenize.TokenInfo) -> bool:
    return tok.line.lstrip().startswith(("from ", "import "))


def _offenders(predicate, allowed) -> list[str]:
    """``apps/hr/<файл>:<строка>: <код>`` для каждого совпадения вне исключений.

    ``allowed`` — либо множество файлов (исключены целиком), либо словарь
    «файл → имена, разрешённые в нём» (тогда ``predicate`` получает и это
    множество, чтобы решить сам).
    """
    found: dict[tuple[str, int], str] = {}
    for path in _working_code_files():
        rel = _rel(path)
        if isinstance(allowed, dict):
            names_ok = allowed.get(rel, frozenset())
        elif rel in allowed:
            continue
        else:
            names_ok = frozenset()
        tokens = _code_tokens(path)
        for i, tok in enumerate(tokens):
            if predicate(tokens, i, names_ok):
                found.setdefault((rel, tok.start[0]), f"apps/hr/{rel}:{tok.start[0]}: {tok.line.strip()}")
    return list(found.values())


# ── 1. эвристика по названию — только перенос ─────────────────────────────


def _calls_heuristic(tokens, i, names_ok) -> bool:
    tok = tokens[i]
    if tok.type != tokenize.NAME or tok.string not in _HEURISTIC_NAMES:
        return False
    prev = tokens[i - 1] if i else None
    if prev is not None and prev.type == tokenize.NAME and prev.string == "def":
        return False  # определение, не вызов
    return tok.string not in names_ok


def test_title_heuristic_is_called_only_by_the_migration_path():
    """``classify_hr_level`` — угадывание кадрового уровня по маркерам в
    названии должности («HR Director» → lead). После задачи 9 это не модель
    прав, а эвристика ОДНОРАЗОВОГО переноса уровней в роли; любой другой
    вызов вернул бы в код второй источник правды о правах. До задачи 9
    падал на ``resolve_hr_access`` — резолвере живого токена."""
    assert _offenders(_calls_heuristic, HEURISTIC_CALLERS_ALLOWED) == []


def test_the_old_resolver_is_gone():
    """``apps.hr.access`` больше не резолвер прав: ни ``HRAccess``, ни
    ``resolve_hr_access``/``require_hr_access``, ни ``HRAccessDenied``.
    Импортом, а не грепом: их отсутствие в модуле — и есть факт."""
    from apps.hr import access

    leftovers = {
        "HRAccess", "HRAccessDenied", "resolve_hr_access", "require_hr_access",
        "require_can_write_basic",
    } & set(dir(access))
    assert leftovers == set(), f"старая модель прав всё ещё в apps.hr.access: {sorted(leftovers)}"


# ── 2. колонку Position.permissions никто не читает ───────────────────────


def _reads_permissions_column(tokens, i, _names_ok) -> bool:
    tok = tokens[i]
    prev = tokens[i - 1] if i else None
    # a) атрибут ``<что-то>.permissions`` — кроме ``from .permissions import``.
    if (tok.type == tokenize.NAME and tok.string == "permissions"
            and prev is not None and prev.type == tokenize.OP and prev.string == "."
            and not _is_import_line(tok)):
        return True
    if tok.type != tokenize.STRING:
        return False
    # b) ``getattr(<x>, "permissions", …)``.
    if tok.string in _PERMISSIONS_STRINGS and i >= 3:
        head = tokens[i - 3]
        if head.type == tokenize.NAME and head.string == "getattr":
            return True
    # c) ``…permissions__hr_level…`` в lookup'ах ORM.
    if "permissions__" in tok.string:
        return True
    # d) ``.values("permissions")``/``.values_list(…)``/``.only(…)``/``.defer(…)``.
    if tok.string in _PERMISSIONS_STRINGS:
        depth = 0
        for j in range(i - 1, -1, -1):
            t = tokens[j]
            if t.type == tokenize.OP and t.string == ")":
                depth += 1
            elif t.type == tokenize.OP and t.string == "(":
                if depth == 0:
                    callee = tokens[j - 1] if j else None
                    return (callee is not None and callee.type == tokenize.NAME
                            and callee.string in _QUERYSET_PROJECTIONS)
                depth -= 1
    return False


def test_position_permissions_column_has_no_readers_but_the_named_ones():
    """Колонка мертва: её читает только ``user_has_permission`` (для
    ``apps.contracts``), сериализатор должности и эвристика переноса.
    Появление нового читателя означало бы, что права снова считаются
    из двух мест."""
    assert _offenders(_reads_permissions_column, COLUMN_READERS_ALLOWED) == []


# ── 3. колонку Position.permissions никто не пишет ────────────────────────


def _writes_permissions_column(tokens, i, _names_ok) -> bool:
    tok = tokens[i]
    nxt = tokens[i + 1] if i + 1 < len(tokens) else None
    prev = tokens[i - 1] if i else None
    # a) форма колонки — ``"hr_level"`` где бы то ни было.
    if tok.type == tokenize.STRING and tok.string in _HR_LEVEL_STRINGS:
        return True
    # b) литерал ``"permissions": {…}`` — словарь под колонку (defaults=/_PRESCRIBED).
    if (tok.type == tokenize.STRING and tok.string in _PERMISSIONS_STRINGS
            and nxt is not None and nxt.type == tokenize.OP and nxt.string == ":"
            and i + 2 < len(tokens) and tokens[i + 2].string == "{"):
        return True
    # c) ``permissions=`` как именованный аргумент вызова и ``.permissions = ``
    #    как присваивание (объявление поля модели — ``permissions = models.…``
    #    на отступе класса — сюда не попадает: перед ним не ``(``/``,``/``.``).
    if (tok.type == tokenize.NAME and tok.string == "permissions"
            and nxt is not None and nxt.type == tokenize.OP and nxt.string == "="
            and prev is not None and prev.type == tokenize.OP and prev.string in {"(", ",", "."}):
        return True
    return False


def test_position_permissions_column_has_no_writers():
    """Сиды (``seed_hr_demo``/``group_structures``), ``participant_service``
    и ETL не пишут ``Position.permissions``: после снятия резолвера
    ``hr_level`` в ней мёртв, а ключи contracts на стенде через роли никто
    не читает. Оставшийся путь записи — API должностей (Ruling B) — колонку
    по имени не называет и потому сторожу не виден намеренно."""
    assert _offenders(_writes_permissions_column, COLUMN_SHAPE_ALLOWED) == []


# ── 4. ручка employees/hr-level удалена ───────────────────────────────────


@pytest.mark.django_db
@pytest.mark.parametrize("path", ["/api/hr/v1/employees/hr-level/", "/api/hr/v1/employees/hr-level"])
def test_hr_level_endpoint_is_gone(path, company_row):
    """Единственный потребитель (``useHRLevel``) снят задачей 8; свой
    уровень вызывающий узнаёт из ``/api/access/v1/me``. 404 — а не 403 и не
    401: маршрута нет вовсе, по обоим написаниям (``APPEND_SLASH=False``)."""
    _user, headers = _user_auth("no-hr-level@htq.test", company_slug=company_row)
    assert Client().get(path, **headers).status_code == 404


def test_hr_level_endpoint_is_not_in_the_self_service_registry():
    from apps.access.self_service import SELF_SERVICE

    assert "employee_hr_level" not in SELF_SERVICE["hr"]
