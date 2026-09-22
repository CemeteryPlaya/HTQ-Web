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

Что сторожится и КОГО исключает поимённо — по ФУНКЦИИ, не по файлу
(фикс-раунд 1 задачи 9: новый читатель, дописанный в тот же файл рядом с
разрешённым, обязан краснеть). Каждое исключение — решение контроллера,
зафиксированное в ``task-9-brief.md``/``progress.md``:

1. ``classify_hr_level`` — эвристика по названию должности — не ВЫЗЫВАЕТСЯ
   нигде, кроме команды переноса (``apps.hr.interface.
   list_positions_hr_levels`` → ``manage.py access_backfill_positions``):
   перенос уровней в роли — единственное законное применение угадывания
   (Ruling C). Её помощник ``_level_from_permissions`` — там же плюс
   внутри самой эвристики.
2. ``Position.permissions`` никто не ЧИТАЕТ — колонка остаётся, но мертва
   (решение заказчика 3). Исключения: ``apps.hr.interface.
   user_has_permission`` — контракт с ``apps.contracts`` до их перехода на
   узлы ``access`` (roadmap §6; Ruling A); ``position_service.serialize`` —
   ``PositionOut.permissions`` остаётся в API, потому что через него в
   колонку попадают ключи contracts (Ruling B); ``access.
   _level_from_permissions`` — эвристика переноса, читает только ``hr_level``
   (Ruling C); ``access._explicit_keys_from_permissions`` — явный список
   ключей, третий источник старой модели, тоже только для переноса
   (Ruling K финальной волны).
3. ``Position.permissions`` никто не ПИШЕТ — сиды, ``participant_service``,
   ``group_structures`` перестали. Форму колонки (``"hr_level"``) называют
   только те же три функции плюс ``list_positions_hr_levels`` (отдаёт
   ``hr_level`` команде переноса) и ``position_service._serialize_permissions``
   (сериализует форму наружу). Единственный оставшийся путь записи — API
   должностей (``PositionIn.permissions`` → ``position_service``, Ruling B):
   он не называет колонку по имени (``model_dump()``), сторожу не виден и
   намеренно не ловится.
4. Ручка ``employees/hr-level`` удалена (единственный потребитель снят
   задачей 8; отдавать её из ролей значило бы второй источник правды рядом
   с ``/api/access/v1/me``) — 404 по обоим написаниям пути.

Разбор — токенами (``tokenize``), а не подстрокой: файлы домена в изобилии
УПОМИНАЮТ старые имена в докстрингах и комментариях, объясняя, чем ручка
отличалась раньше, — проза сторожа не интересует, только код. Что именно
ловит каждое правило, проверено мутациями (инъекция в ``pmo_service.py`` →
красный → откат) — протокол в отчёте задачи 9, раздел «Фикс-раунд 1».
"""

from __future__ import annotations

import pathlib
import re
import tokenize

import pytest
from django.test import Client

from apps.hr.tests.test_employees_api import _user_auth

BACKEND = pathlib.Path(__file__).resolve().parents[3]
HR = BACKEND / "apps" / "hr"

#: Кому можно ЗВАТЬ эвристику переноса (по имени ВЫЗЫВАЕМОГО; определения
#: ``def …`` не в счёт).
HEURISTIC_CALLERS_ALLOWED: dict[str, frozenset[str]] = {
    # list_positions_hr_levels — источник для access_backfill_positions.
    "interface.py": frozenset({"classify_hr_level", "_level_from_permissions"}),
    # сама эвристика зовёт свой помощник (явный hr_level приоритетнее названия).
    "access.py": frozenset({"_level_from_permissions"}),
}

#: Читатели колонки ``Position.permissions`` — «файл → функции» (п. 2).
COLUMN_READERS_ALLOWED: dict[str, frozenset[str]] = {
    "interface.py": frozenset({"user_has_permission"}),           # Ruling A
    "services/position_service.py": frozenset({"serialize"}),     # Ruling B
    # Ruling C; Ruling K (финальная волна) — явный список ключей для переноса.
    "access.py": frozenset({"_level_from_permissions", "_explicit_keys_from_permissions"}),
}

#: Кто вправе называть форму колонки (``"hr_level"``, ``"permissions": …``)
#: — те же три плюс двое, кто отдаёт форму наружу, не трогая колонку (п. 3).
COLUMN_SHAPE_ALLOWED: dict[str, frozenset[str]] = {
    "interface.py": frozenset({"user_has_permission", "list_positions_hr_levels"}),
    "services/position_service.py": frozenset({"serialize", "_serialize_permissions"}),
    "access.py": frozenset({"_level_from_permissions"}),
}

_HEURISTIC_NAMES = frozenset({"classify_hr_level", "_level_from_permissions"})
_PERMISSIONS_STRINGS = frozenset({'"permissions"', "'permissions'"})
_HR_LEVEL_STRINGS = frozenset({'"hr_level"', "'hr_level'"})
#: Вызовы, где строка ``"permissions"`` аргументом — чтение колонки.
_READING_CALLEES = frozenset({"getattr", "values", "values_list", "only", "defer"})
#: Вызовы ORM, где ключ ``"permissions": …`` в словаре — запись колонки.
_WRITING_CALLEES = frozenset({"create", "update_or_create", "get_or_create", "update", "bulk_create"})
_OPENERS = {"(", "[", "{"}
_CLOSERS = {")", "]", "}"}
_SKIPPED = frozenset({
    tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE, tokenize.INDENT,
    tokenize.DEDENT, tokenize.ENCODING, tokenize.ENDMARKER,
})
_DEF_RE = re.compile(r"^(\s*)(?:async\s+)?def\s+(\w+)\s*\(")


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


def _enclosing_function(lines: list[str], lineno: int) -> str | None:
    """Имя функции, в ТЕЛЕ которой стоит строка ``lineno``, — или ``None``.

    Подъём вверх по блокам: первая непустая строка (не комментарий) с
    МЕНЬШИМ отступом — заголовок объемлющего блока. ``def``/``async def`` —
    ответ; иначе (``class``, ``if``, ``with``, перенос выражения) — подъём
    продолжается уже от её отступа. Раньше граница была «ближайший ``def``
    меньшего отступа», и строка в теле КЛАССА, объявленного сразу после
    разрешённой функции модуля, приписывалась этой функции — поимённое
    исключение молча накрывало чужой код (T9-A финальной волны блока I).

    ``None`` для кода на уровне модуля или класса (``_PRESCRIBED = {…}``,
    ``_PERMISSION_CATALOG``, атрибуты класса): у него нет функции, которую
    можно было бы разрешить поимённо, — такой код не исключается никогда.
    """
    line = lines[lineno - 1]
    indent = len(line) - len(line.lstrip())
    for up in range(lineno - 2, -1, -1):
        if indent == 0:
            return None
        candidate = lines[up]
        stripped = candidate.strip()
        if not stripped or stripped.startswith("#"):
            continue
        cand_indent = len(candidate) - len(candidate.lstrip())
        if cand_indent >= indent:
            continue
        m = _DEF_RE.match(candidate)
        if m:
            return m.group(2)
        indent = cand_indent
    return None


def _enclosing_callee(tokens: list[tokenize.TokenInfo], i: int) -> str | None:
    """Имя функции, в скобках вызова которой стоит токен ``i``.

    Назад по токенам с учётом вложенности: закрывающие скобки увеличивают
    глубину, открывающие — уменьшают; ``{``/``[`` на нулевой глубине —
    это контейнер, В КОТОРОМ мы стоим (``defaults={"permissions": …}``), его
    проходим и ищем дальше первую ``(`` на нулевой глубине — перед ней и
    стоит вызываемое имя. ``None`` — не внутри вызова (уровень модуля,
    присваивание).
    """
    depth = 0
    for j in range(i - 1, -1, -1):
        t = tokens[j]
        if t.type != tokenize.OP:
            continue
        if t.string in _CLOSERS:
            depth += 1
        elif t.string in _OPENERS:
            if depth > 0:
                depth -= 1
            elif t.string == "(":
                callee = tokens[j - 1] if j else None
                return callee.string if callee is not None and callee.type == tokenize.NAME else None
            # ``{``/``[`` на нулевой глубине — контейнер, идём наружу.
    return None


def _offenders(predicate, allowed: dict[str, frozenset[str]], *, by: str) -> list[str]:
    """``apps/hr/<файл>:<строка>: <код>`` для каждого совпадения вне исключений.

    ``allowed`` — «файл → имена»; ``by="function"`` — имя ОБЪЕМЛЮЩЕЙ функции
    токена (исключение по функции), ``by="callee"`` — имя самого токена
    (исключение по тому, КОГО зовут; для эвристики переноса).
    """
    found: dict[tuple[str, int], str] = {}
    for path in _working_code_files():
        rel = _rel(path)
        names_ok = allowed.get(rel, frozenset())
        tokens = _code_tokens(path)
        lines = path.read_text(encoding="utf-8").splitlines()
        for i, tok in enumerate(tokens):
            if not predicate(tokens, i):
                continue
            name = tok.string if by == "callee" else _enclosing_function(lines, tok.start[0])
            if name in names_ok:
                continue
            found.setdefault((rel, tok.start[0]), f"apps/hr/{rel}:{tok.start[0]}: {tok.line.strip()}")
    return list(found.values())


# ── 1. эвристика по названию — только перенос ─────────────────────────────


def _calls_heuristic(tokens, i) -> bool:
    tok = tokens[i]
    if tok.type != tokenize.NAME or tok.string not in _HEURISTIC_NAMES:
        return False
    prev = tokens[i - 1] if i else None
    return not (prev is not None and prev.type == tokenize.NAME and prev.string == "def")


def test_title_heuristic_is_called_only_by_the_migration_path():
    """``classify_hr_level`` — угадывание кадрового уровня по маркерам в
    названии должности («HR Director» → lead). После задачи 9 это не модель
    прав, а эвристика ОДНОРАЗОВОГО переноса уровней в роли; любой другой
    вызов вернул бы в код второй источник правды о правах. До задачи 9
    падал на ``resolve_hr_access`` — резолвере живого токена."""
    assert _offenders(_calls_heuristic, HEURISTIC_CALLERS_ALLOWED, by="callee") == []


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


def _reads_permissions_column(tokens, i) -> bool:
    tok = tokens[i]
    prev = tokens[i - 1] if i else None
    if tok.type == tokenize.NAME:
        # a) атрибут ``<что-то>.permissions`` — кроме ``from .permissions import``.
        if (tok.string == "permissions" and prev is not None
                and prev.type == tokenize.OP and prev.string == "."
                and not _is_import_line(tok)):
            return True
        # b) ORM-lookup именованным аргументом: ``filter(permissions__hr_level=…)``.
        return tok.string.startswith("permissions__")
    if tok.type != tokenize.STRING:
        return False
    # c) ``…permissions__hr_level…`` строкой: ``order_by("permissions__…")``.
    if "permissions__" in tok.string:
        return True
    # d) ``"permissions"`` аргументом вызова, который читает атрибут/колонку:
    #    ``getattr(x, "permissions"[, default])``, ``.values("permissions")``,
    #    ``.values_list(…)``, ``.only(…)``, ``.defer(…)``.
    return tok.string in _PERMISSIONS_STRINGS and _enclosing_callee(tokens, i) in _READING_CALLEES


def test_position_permissions_column_has_no_readers_but_the_named_ones():
    """Колонка мертва: её читают только ``user_has_permission`` (для
    ``apps.contracts``), ``position_service.serialize`` и эвристика переноса
    ``_level_from_permissions``. Появление нового читателя — хоть в том же
    файле, в соседней функции — означало бы, что права снова считаются из
    двух мест."""
    assert _offenders(_reads_permissions_column, COLUMN_READERS_ALLOWED, by="function") == []


# ── 3. колонку Position.permissions никто не пишет ────────────────────────


def _writes_permissions_column(tokens, i) -> bool:
    tok = tokens[i]
    nxt = tokens[i + 1] if i + 1 < len(tokens) else None
    prev = tokens[i - 1] if i else None
    # a) форма колонки — ``"hr_level"`` где бы то ни было.
    if tok.type == tokenize.STRING and tok.string in _HR_LEVEL_STRINGS:
        return True
    # b) ключ ``"permissions": …`` в словаре: либо значение — литерал ``{``
    #    (форма колонки), либо словарь стоит внутри вызова ORM-писателя
    #    (``update_or_create(defaults={"permissions": perms})`` — значение
    #    любое: переменная, вызов).
    if (tok.type == tokenize.STRING and tok.string in _PERMISSIONS_STRINGS
            and nxt is not None and nxt.type == tokenize.OP and nxt.string == ":"):
        after = tokens[i + 2] if i + 2 < len(tokens) else None
        if after is not None and after.string == "{":
            return True
        return _enclosing_callee(tokens, i) in _WRITING_CALLEES
    # c) ``permissions=`` как именованный аргумент вызова и ``.permissions = ``
    #    как присваивание (объявление поля модели — ``permissions = models.…``
    #    на отступе класса — сюда не попадает: перед ним не ``(``/``,``/``.``).
    return (tok.type == tokenize.NAME and tok.string == "permissions"
            and nxt is not None and nxt.type == tokenize.OP and nxt.string == "="
            and prev is not None and prev.type == tokenize.OP and prev.string in {"(", ",", "."})


def test_position_permissions_column_has_no_writers():
    """Сиды (``seed_hr_demo``/``group_structures``), ``participant_service``
    и ETL не пишут ``Position.permissions``: после снятия резолвера
    ``hr_level`` в ней мёртв, а ключи contracts на стенде через роли никто
    не читает. Оставшийся путь записи — API должностей (Ruling B) — колонку
    по имени не называет и потому сторожу не виден намеренно."""
    assert _offenders(_writes_permissions_column, COLUMN_SHAPE_ALLOWED, by="function") == []


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


# ── T9-A: граница объемлющей функции ─────────────────────────────────────


def test_enclosing_function_does_not_leak_into_a_following_class():
    """Строка в теле класса сразу после разрешённой функции модуля — НЕ
    её тело: поимённое исключение функции не должно её накрывать."""
    lines = [
        "def user_has_permission(user_id, permission):",
        "    return position.permissions",
        "",
        "class Leaky:",
        "    value = position.permissions",
    ]
    assert _enclosing_function(lines, 2) == "user_has_permission"
    assert _enclosing_function(lines, 5) is None


def test_enclosing_function_climbs_through_nested_blocks_and_async_def():
    lines = [
        "class Service:",
        "    async def serialize(self, position):",
        "        if position:",
        "            data = foo(",
        "                position.permissions,",
        "            )",
    ]
    assert _enclosing_function(lines, 5) == "serialize"
    assert _enclosing_function(lines, 1) is None
