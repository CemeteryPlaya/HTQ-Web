"""Задача 9 плана A: необязательный гейт ``module``/``level`` в ``api_view``.

Гейт ОБЪЯВЛЯЕТСЯ, но ни на одну существующую ручку в этой стадии не
навешивается — это отдельная работа поверх переработанного HR (спека A8).
Поэтому здесь он проверяется на собственных пробных вьюхах.

Начиная с блока I «Единая модель прав» (задача 3,
``.superpowers/sdd/2026-09-17-block-i-single-rbac/task-3-brief.md``) файл
несёт ещё и ПЕРЕВЁРНУТЫЙ сторож: не «гейта нет нигде», а «гейт есть у КАЖДОЙ
ручки переведённой аппки, кроме объявленного самообслуживания» — реестр
переведённых аппок и список исключений лежат в ``apps.access.self_service``
(докстринг там объясняет оба решения и их обоснование).
"""

import ast
import pathlib
import re

import pytest
from django.test import RequestFactory
from django.views import View as _DjangoView

import htqweb.http as _http
from apps.access import self_service
from apps.access.models import Level, Role, RoleAssignment, ScopeKind
from apps.access.tests.helpers import auth, superuser_token, token
from apps.access.tests.helpers import grant
from htqweb.http import api_view


def _view(**gate):
    @api_view(methods=("GET",), **gate)
    def probe(request):
        return {"ok": True}

    return probe


def _request(tok: str, company: str | None = None):
    request = RequestFactory().get("/probe", **auth(tok))
    if company is not None:
        request.company = {"slug": company}
    return request


def _grant(user_id: int, company: str, module: str, level: str) -> None:
    role = Role.objects.create(code=f"r{user_id}{module}{level}", title="Роль")
    grant(role, module, level)
    RoleAssignment.objects.create(company_slug=company, user_id=user_id, role=role,
                                  scope_kind=ScopeKind.COMPANY, scope_id=None)


@pytest.mark.django_db
def test_view_without_gate_is_untouched():
    """Ручки без module= ведут себя ровно как раньше — регресс всего API."""
    assert _view()(_request(token())).status_code == 200


@pytest.mark.django_db
def test_gate_allows_equal_level(company_context):
    slug = company_context["slug"]
    _grant(7, slug, "hr", Level.WRITE)
    resp = _view(module="hr", level="write")(_request(token(company=slug), slug))
    assert resp.status_code == 200


@pytest.mark.django_db
def test_gate_allows_higher_level(company_context):
    slug = company_context["slug"]
    _grant(7, slug, "hr", Level.ADMIN)
    resp = _view(module="hr", level="write")(_request(token(company=slug), slug))
    assert resp.status_code == 200


@pytest.mark.django_db
def test_gate_rejects_lower_level(company_context):
    slug = company_context["slug"]
    _grant(7, slug, "hr", Level.READ)
    resp = _view(module="hr", level="write")(_request(token(company=slug), slug))
    assert resp.status_code == 403


@pytest.mark.django_db
def test_gate_rejects_absent_module(company_context):
    slug = company_context["slug"]
    resp = _view(module="hr", level="read")(_request(token(company=slug), slug))
    assert resp.status_code == 403


@pytest.mark.django_db
def test_gate_lets_superuser_through(company_context):
    slug = company_context["slug"]
    resp = _view(module="hr", level="admin")(
        _request(superuser_token(company=slug), slug))
    assert resp.status_code == 200


@pytest.mark.django_db
def test_gate_failure_answers_with_the_error_envelope(company_context, service_off):
    """Выключенный домен ``access`` — 503 в конверте, а не голый 500.

    Раунд правок 1 задачи 4 блока I. Гейт ходит в базу через
    ``apps.access.interface``, а тот первой строкой зовёт
    ``require_service("access")``. Пока ``try`` в ``api_view`` начинался ПОСЛЕ
    гейта, ``ServiceDisabled`` уходил из вьюхи наружу целиком: клиент получал
    500 без конверта ``{"detail": …}``, одинаковый для «домен прав выключен» и
    «вьюха упала», и даже без строки лога. Проверяется на гейтированной ручке
    ЧУЖОГО модуля (``hr``): у ручек самой ``access`` 503 отдал бы
    ``ServiceGateMiddleware`` по префиксу URL, то есть эта дыра там не видна.
    """
    import json

    slug = company_context["slug"]
    with service_off("access"):
        resp = _view(module="hr", level="read")(_request(token(company=slug), slug))
    assert resp.status_code == 503
    body = json.loads(resp.content)
    assert body["code"] == "service_disabled"
    assert body["service"] == "access"
    assert "detail" in body


@pytest.mark.django_db
def test_gate_without_company_context_rejects():
    """Прав вне компании не бывает — подставлять «по умолчанию» запрещено."""
    resp = _view(module="hr", level="read")(_request(token()))
    assert resp.status_code == 403


# Аппки, чьи ручки и гейты авторизации разработаны вместе.
# Гейт на них не ретрофит на старые ручки — он часть исходного дизайна.
# Список должен быть КОРОТКИМ: каждая запись — это декларация, что у аппки
# нет старых ручек без авторизации, к которым гейт был приклеен потом.
# Пуст с финальной волны блока I (рулинг J): единственная запись,
# ``apps/companies/views.py``, ушла под перевёрнутый сторож ниже
# (``self_service.TRANSLATED_APPS``) — декларацию сменило требование.
_GATE_ALLOWLIST: set[str] = set()

# Пять аппок блока I «Единая модель прав» — их судьбу решает
# apps.access.self_service (TRANSLATED_APPS/SELF_SERVICE), а не бланковый
# запрет ниже: задачи 4-7 вешали на них module=/level= по одной за коммит,
# companies добавлена финальной волной (рулинг J).
_RBAC_APPS = frozenset(self_service.SELF_SERVICE)

# apps/signoff, apps/contracts — гейт на них ведёт параллельно другой
# разработчик (см. CLAUDE.md и бриф задачи 3): этот файл не должен ни
# требовать его от них, ни спотыкаться, если он там уже появится на их
# ветке раньше, чем здесь. Поэтому они попросту вне области действия обеих
# проверок ниже.
_OUT_OF_SCOPE_APPS = frozenset({"signoff", "contracts"})


def test_gate_is_not_hung_on_apps_without_a_translation_plan():
    """Гейт не навешивается на ручку аппки, для которой это ещё не решено.

    Продолжение того же инварианта, что был раньше («гейт нигде»), но уже
    не «нигде» — а «нигде за пределами пяти аппок блока I и параллельной
    ветки signoff/contracts»: у первых своя, перевёрнутая проверка ниже
    (``test_gate_covers_every_handle_of_translated_apps``), у вторых —
    работа другого разработчика, в которую этот файл не вмешивается.
    Для всех ОСТАЛЬНЫХ аппок (``approvals``, ``cms``, ``conference``,
    ``core``, ``mail``, ``media_files``, ``messenger``) ретрофит гейта
    по-прежнему не спланирован — преждевременный ``module=`` там ловится
    здесь же, как и раньше.

    Список исключений (``_GATE_ALLOWLIST``) обязан быть коротким и содержать
    только аппки, где есть уверенность, что все существующие ручки правильно
    гейтированы.
    """
    backend = pathlib.Path(__file__).resolve().parents[3]
    offenders = []
    for path in (backend / "apps").rglob("views.py"):
        posix_path = path.relative_to(backend).as_posix()
        if posix_path in _GATE_ALLOWLIST:
            continue
        if path.parent.name in _RBAC_APPS or path.parent.name in _OUT_OF_SCOPE_APPS:
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "module=" in line and "api_view" in line:
                offenders.append(f"{posix_path}:{lineno}")
    assert offenders == [], f"гейт навешен раньше времени: {offenders}"


# ── Перевёрнутый сторож: гейт ЕСТЬ у каждой ручки переведённой аппки ───────
#
# Разбор ручек — тот же признак, что у проверки выше: строка(и) исходника с
# ``api_view(...)``, а НЕ импорт/интроспекция вьюх. Импортировать
# apps.access.views здесь означало бы тот же цикл, которого избегает сам
# htqweb.http.api_view (см. test_access_is_not_imported_at_module_level
# ниже) — и распространялось бы на hr/tasks/users без всякой причины.


def _iter_api_view_calls(text: str):
    """(start_lineno, end_lineno, call_text) для каждого вызова ``api_view(...)``.

    Две правки поверх наивного «ищем подстроку в каждой строке»:

    1. Декоратор в этой кодовой базе иногда переносится на вторую строку
       (``apps/hr/views.py`` — ``body=``/``status=`` уезжают под
       ``api_view(``). Построчная проверка «module= в ЭТОЙ строке» невидима
       к module=, оказавшемуся на второй строке — а это ровно тот случай,
       когда пропуск опасен: ручку сочтут незагейченной, хотя гейт на ней
       есть, или наоборот, самообслуживание сочтут «чистым», хотя гейт
       на него только что навесили. Склейка по балансу скобок ЭТОГО
       конкретного вызова (не всей конструкции целиком — ``method_
       decorator(api_view(...))`` не должен утянуть чужую закрывающую
       скобку) закрывает оба направления, оставаясь тем же текстовым
       разбором, а не импортом.
    2. Файл ``hr`` в изобилии УПОМИНАЕТ ``api_view(...)`` в докстрингах и
       построчных комментариях (объясняя, чем ручка отличается от
       соседней) — наивный поиск подстроки принял бы такую прозу за вызов.
       Пропускаем целые строки-комментарии (``#...``) и текст внутри
       тройных кавычек.
    """
    lines = text.splitlines()
    i = 0
    n = len(lines)
    in_docstring = False
    while i < n:
        line = lines[i]
        started_inside = in_docstring
        if line.count('"""') % 2 == 1:
            in_docstring = not in_docstring
        if started_inside or line.strip().startswith("#"):
            i += 1
            continue
        idx = line.find("api_view(")
        if idx == -1:
            i += 1
            continue
        start_lineno = i + 1
        buf = line[idx:]
        depth = buf.count("(") - buf.count(")")
        j = i
        while depth > 0 and j + 1 < n:
            j += 1
            nxt = lines[j]
            buf += "\n" + nxt
            depth += nxt.count("(") - nxt.count(")")
            if nxt.count('"""') % 2 == 1:
                in_docstring = not in_docstring
        yield start_lineno, j + 1, buf
        i = j + 1


_DEF_RE = re.compile(r"^\s*def\s+(\w+)\s*\(")
_DEF_OR_CLASS_RE = re.compile(r"^(\s*)(def|class)\s+(\w+)")
_ASSIGN_RE = re.compile(r"^(\w+)\s*=")


def _enclosing_scope(lines: list[str], from_idx: int, inner_indent: int) -> str | None:
    """Ближайший (не любой!) объемлющий ``class``/``def`` строже отступа.

    Нужен для вложенных замыканий вроде ``apps/tasks/views.py::
    _reference_endpoints`` (``_list``/``_create``/... объявлены ВНУТРИ
    обычной функции, а не класса) — если брать первый попавшийся ``class``
    выше по файлу без учёта отступа, замыкание внутри функции по ошибке
    приписывается постороннему классу, объявленному раньше на нулевом
    отступе (см. ``_ParamError`` выше ``_reference_endpoints`` в том же
    файле). Ближайший по СТРОКЕ, а не по отступу «ровно на уровень
    меньше» — отступы в этой кодовой базе не всегда кратны одному шагу.
    """
    for up in range(from_idx, -1, -1):
        m = _DEF_OR_CLASS_RE.match(lines[up])
        if m and len(m.group(1)) < inner_indent:
            return m.group(3)
    return None


def _qualified_name(lines: list[str], start_lineno: int, end_lineno: int) -> str | None:
    """Имя-ключ ручки для сверки с ``self_service.SELF_SERVICE``.

    Три формы, которыми объявлена ручка в этих пяти аппках:

    - ``@api_view(...)`` прямо над ``def name(...)`` — hr/users/tasks, а
      также отдельно объявленная class-based ручка (``MyCompaniesView.get``
      -стиль) → ``Класс.метод`` или ``функция``;
    - ``NAME = method_decorator(api_view(...))`` — общий ``read`` access →
      ``NAME``;
    - ``return method_decorator(api_view(...))`` внутри ``def helper(...):``
      — фабрика вроде ``access.views.write()`` → ``helper``.

    ``None``, если ни одна форма не подошла: вызывающий код тогда просто не
    сможет сверить ручку с ``SELF_SERVICE`` (не потребует и не запретит
    гейт по имени), а не упадёт на конструкции, которой в этих файлах
    сегодня не бывает.
    """
    idx = start_lineno - 1
    first_stripped = lines[idx].strip()
    if first_stripped.startswith("@"):
        k = end_lineno  # СРАЗУ после закрывающей скобки ЭТОГО декоратора —
        # не start_lineno + 1, иначе многострочный декоратор (body=/status=
        # на следующей строке) принимается за "def не нашли".
        while k < len(lines):
            candidate = lines[k].strip()
            if not candidate or candidate.startswith("@") or candidate.startswith("#"):
                k += 1
                continue
            m = _DEF_RE.match(lines[k])
            if not m:
                return None
            method_name = m.group(1)
            def_indent = len(lines[k]) - len(lines[k].lstrip())
            if def_indent == 0:
                return method_name
            scope = _enclosing_scope(lines, idx, def_indent)
            if scope:
                return f"{scope}.{method_name}"
            return method_name
        return None
    m = _ASSIGN_RE.match(first_stripped)
    if m:
        return m.group(1)
    for up in range(idx, -1, -1):
        m2 = _DEF_RE.match(lines[up])
        if m2 and (len(lines[up]) - len(lines[up].lstrip())) == 0:
            return m2.group(1)
    return None


def test_gate_covers_every_handle_of_translated_apps():
    """Переведённая аппка: у каждой её ручки — ``module=``, кроме self_service.

    Падает в ОБЕ стороны:
    - ``missing`` — ручка без ``module=``, которой нет в ``SELF_SERVICE``:
      забытая ручка, ретрофит на неё не доехал;
    - ``stale`` — ручка есть в ``SELF_SERVICE``, но ``module=`` у неё
      всё-таки появился: либо список устарел (переименовали, гейт
      действительно нужен), либо гейт навешан по ошибке на то, что должно
      остаться открытым без единой роли;
    - ``unknown_exempt`` — запись ``SELF_SERVICE`` не находит соответствующей
      ручки в файле вовсе (переименовали функцию, либо, для class-based
      ручек ``access``, self-service-ручку не выделили в отдельный вызов
      ``api_view(...)`` — см. докстринг ``apps.access.self_service``).

    Аппка, которой ещё нет в ``TRANSLATED_APPS``, не проверяется вовсе —
    задача 5 осознанно гейтирует часть ``hr`` до того, как эта запись
    появится (см. докстринг ``self_service``), и это не расхождение.
    """
    backend = pathlib.Path(__file__).resolve().parents[3]
    missing: list[str] = []
    stale: list[str] = []
    unknown_exempt: list[str] = []

    for app, exempt in self_service.SELF_SERVICE.items():
        if app not in self_service.TRANSLATED_APPS:
            continue
        path = backend / "apps" / app / "views.py"
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        seen: set[str] = set()
        for start_lineno, end_lineno, block in _iter_api_view_calls(text):
            if "auth=None" in block:
                continue  # без JWT гейт module= структурно не выполнится (htqweb/http.py)
            name = _qualified_name(lines, start_lineno, end_lineno)
            if name:
                seen.add(name)
            location = f"apps/{app}/views.py:{start_lineno}" + (f" ({name})" if name else "")
            is_exempt = name in exempt
            has_gate = "module=" in block
            if is_exempt and has_gate:
                stale.append(location)
            elif not is_exempt and not has_gate:
                missing.append(location)
        for name in sorted(set(exempt) - seen):
            unknown_exempt.append(f"apps/{app}/views.py: {name}")

    assert not missing, f"ручкам не хватает гейта модуля: {missing}"
    assert not stale, f"self_service устарел — гейт есть у объявленного самообслуживания: {stale}"
    assert not unknown_exempt, (
        "self_service ссылается на несуществующую ручку (переименовали "
        f"функцию, либо не выделили её в отдельный api_view(...)): {unknown_exempt}"
    )


def test_self_service_reasons_are_declared():
    """Каждая запись ``SELF_SERVICE`` обязана нести причину из ``REASONS``.

    Раунд правок 1 задачи 3: ревью показало, что запись ``hr.org_tree`` была
    ВЕРНОЙ (гейт ей правда не положен — см. докстринг ``self_service``), а
    ярлык «самообслуживание» на ней — ложью (ручка отдаёт заведомо чужие
    данные, просто сегодня БЕЗ единой проверки прав). Ложь в реестре
    исключений дороже всего: это единственное место, где дыру можно
    объявить легальной, не объяснившись. Закрытый список причин
    (``self``/``open``/``scoped`` — третью добавил раунд правок 1 задачи 6)
    не даёт добавить исключение молча — сторож требует ОДНУ из них у каждой
    записи, а не любую строку.
    """
    bad = [
        f"{app}.{name} = {reason!r}"
        for app, exempt in self_service.SELF_SERVICE.items()
        for name, reason in exempt.items()
        if reason not in self_service.REASONS
    ]
    assert not bad, f"недопустимая причина исключения (не self/open/scoped): {bad}"


def test_access_is_not_imported_at_module_level():
    """Вьюхи apps.access сами декорированы api_view — импорт наверху даст цикл."""
    import htqweb.http as http

    head = pathlib.Path(http.__file__).read_text(encoding="utf-8").splitlines()
    imports = [line for line in head if line.startswith(("import ", "from "))]
    assert not any("apps.access" in line for line in imports)


def test_every_module_gate_names_its_level():
    """У каждого ``api_view(module=…)`` явно указан ``level=`` (T4, финальная
    волна блока I).

    У ``api_view`` есть уровень по умолчанию, и ручка, забывшая ``level=``,
    молча получила бы его — для записи или администрирования это было бы
    расширение, не видное в декораторе. Сегодня ни одна ручка на умолчание
    не полагается (финальное ревью проверило скриптом); сторож держит это
    правилом. ``contracts``/``signoff`` — зона другого разработчика, вне
    области, как и у проверок выше.

    Блок I.2, R7: раньше проверка была текстовой — «в вызове есть подстрока
    ``level=``». Фабрика ``level=level`` проходила её при любом значении
    параметра, в том числе без умолчания в сигнатуре или с ``"none"``;
    ``**gate`` не проверялся вовсе. Теперь уровень РАЗРЕШАЕТСЯ
    (``_level_offenders``): литерал, константа модуля или параметр фабрики с
    литеральным умолчанием в сигнатуре — плюс литералы, которые фабрике
    передают её вызовы; и он обязан быть ``read``/``write``/``admin``.
    """
    backend = pathlib.Path(__file__).resolve().parents[3]
    offenders = []
    for path in sorted((backend / "apps").rglob("views.py")):
        if path.parent.name in _OUT_OF_SCOPE_APPS:
            continue
        text = path.read_text(encoding="utf-8")
        for lineno, name, why in _level_offenders(text):
            offenders.append(f"{path.relative_to(backend).as_posix()}:{lineno} ({name}): {why}")
    assert offenders == [], f"гейт модуля без явного уровня: {offenders}"


def test_every_view_method_of_translated_apps_is_decorated():
    """Метод-ручка класса-вьюхи переведённой аппки несёт декоратор с ``api_view``.

    Блок I.2, R7. Без декоратора у метода нет ни гейта модуля, ни даже
    авторизации (``ApiView`` сам ``api_view`` не зовёт), а сторож полноты
    выше, читающий вызовы ``api_view(``, такой ручки не видит — ему нечего
    сверять. Исключения — тот же реестр самообслуживания, что у сторожа
    полноты; запись там для метода БЕЗ ``api_view`` всё равно упадёт в
    ``unknown_exempt`` соседнего теста (сверять её не с чем), так что
    реестр не становится обходом.
    """
    backend = pathlib.Path(__file__).resolve().parents[3]
    offenders = []
    for app in sorted(self_service.TRANSLATED_APPS):
        path = backend / "apps" / app / "views.py"
        exempt = self_service.SELF_SERVICE.get(app, {})
        for lineno, name in _iter_undecorated_api_methods(path.read_text(encoding="utf-8")):
            if name not in exempt:
                offenders.append(f"apps/{app}/views.py:{lineno} ({name})")
    assert offenders == [], f"ручка класса-вьюхи без api_view: {offenders}"


def test_text_parser_sees_every_api_view_call():
    """Текстовый ``_iter_api_view_calls`` не пропускает настоящих вызовов.

    Оба сторожа выше стоят на нём, а он пропускает строки-комментарии и
    тройные кавычки эвристикой по счёту ``\"\"\"``. Сверка с ``ast`` (который
    комментарии и строки отбрасывает сам) по каждому файлу: число вызовов
    совпадает — эвристика не проглотила живой гейт (или его отсутствие).
    """
    backend = pathlib.Path(__file__).resolve().parents[3]
    mismatched = []
    for path in sorted((backend / "apps").rglob("views.py")):
        if path.parent.name in _OUT_OF_SCOPE_APPS:
            continue
        text = path.read_text(encoding="utf-8")
        by_text = sum(1 for _call in _iter_api_view_calls(text))
        by_ast = sum(1 for node in ast.walk(ast.parse(text))
                     if isinstance(node, ast.Call) and _base_name(node.func) == "api_view")
        if by_text != by_ast:
            mismatched.append(f"{path.relative_to(backend).as_posix()}: текст {by_text}, ast {by_ast}")
    assert mismatched == [], f"текстовый разбор расходится с ast: {mismatched}"


# ── Блок I.2, R7: слепые пятна сторожей ────────────────────────────────────
#
# Сторож полноты выше читает ВЫЗОВЫ ``api_view(``. Два места он не видел:
# метод класса-вьюхи вовсе без декоратора (вызова нет — нечего и проверять,
# а ручка при этом живая и без гейта) и уровень, который приходит в
# ``api_view`` не литералом рядом с ``module=``, а именем — параметром
# фабрики-декоратора (``access/views.py::write``) или константой. Тесты на
# синтетических образцах ниже доказывают, что сторож эти формы видит; два
# сторожа на реальном коде — ``test_every_view_method_of_translated_apps_is_
# decorated`` и ``test_every_module_gate_names_its_level``.
#
# Здесь разбор — ``ast``, а не построчный текст: вопросы «от кого унаследован
# класс», «какие декораторы над методом», «какое умолчание у параметра
# фабрики» построчно решаются хрупко (многострочные сигнатуры и декораторы).
# Импорта вьюх по-прежнему нет — ``ast.parse`` читает исходник, не исполняя
# его, так что довод ``test_access_is_not_imported_at_module_level`` в силе.

#: Корни классов-вьюх: джанговский ``View`` и каждый его наследник, объявленный
#: в ``htqweb.http`` (сегодня — ``ApiView``). Список снимается с модуля, а не
#: пишется руками: новый общий базовый класс там не станет слепым пятном.
#: Базы доменов (``CompaniesView``, ``AccessView``) сторож находит сам —
#: по наследованию от уже известных вьюх в том же файле.
_VIEW_ROOTS: frozenset[str] = frozenset(
    {"View"} | {
        name for name, obj in vars(_http).items()
        if isinstance(obj, type) and issubclass(obj, _DjangoView)
    }
)

#: Имена методов, которые ``View.dispatch`` сделает ручкой. Полный список
#: Django, а не суженный ``ApiView.http_method_names``: наследник вправе его
#: расширить, и метод ``options``/``head`` тогда тоже станет ручкой.
_HANDLER_METHODS: frozenset[str] = frozenset(_DjangoView.http_method_names)

#: Уровни, которые гейт реально требует. ``none`` — гейт, который пускает
#: всех, то есть не гейт.
_GATE_LEVELS: frozenset[str] = frozenset({Level.READ.value, Level.WRITE.value,
                                          Level.ADMIN.value})


def _base_name(node) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _calls_api_view(node) -> bool:
    return any(isinstance(sub, ast.Call) and _base_name(sub.func) == "api_view"
               for sub in ast.walk(node))


def _gate_decorator_names(tree: ast.Module) -> set[str]:
    """Имена модуля, которые сами несут ``api_view``: декоратор-переменная
    (``read = method_decorator(api_view(...))``) или фабрика, чей ``return``
    его строит (``def write(...): return method_decorator(api_view(...))``,
    ``platform(...)``)."""
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign) and _calls_api_view(node.value):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and any(
            isinstance(sub, ast.Return) and sub.value is not None
            and _calls_api_view(sub.value)
            for sub in ast.walk(node)
        ):
            names.add(node.name)
    return names


def _is_gate_decorator(decorator, gate_names: set[str]) -> bool:
    if _calls_api_view(decorator):
        return True
    head = decorator.func if isinstance(decorator, ast.Call) else decorator
    return isinstance(head, ast.Name) and head.id in gate_names


def _view_classes(tree: ast.Module) -> list[ast.ClassDef]:
    """Классы файла, унаследованные (прямо или через другой класс файла) от
    корня ``_VIEW_ROOTS``."""
    classes = [node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
    known = set(_VIEW_ROOTS)
    views: dict[str, ast.ClassDef] = {}
    changed = True
    while changed:
        changed = False
        for cls in classes:
            if cls.name not in views and any(_base_name(b) in known for b in cls.bases):
                views[cls.name] = cls
                known.add(cls.name)
                changed = True
    return sorted(views.values(), key=lambda cls: cls.lineno)


def _iter_undecorated_api_methods(text: str):
    """(lineno, ``Класс.метод``) для каждой ручки класса-вьюхи без гейта-декоратора.

    Сторож полноты читает вызовы ``api_view(``; метод CBV без декоратора он
    не видел вовсе — то есть ручка без гейта (и без авторизации: ``ApiView``
    сам ``api_view`` не зовёт) была для него невидимой (блок I.2, R7).
    Ручка — метод из ``_HANDLER_METHODS`` в классе из ``_view_classes``.
    Декоратор засчитывается, только если несёт ``api_view``: сам вызов
    внутри или имя из ``_gate_decorator_names`` — ``@method_decorator(
    csrf_exempt)`` гейтом не считается. Ручка, заведённая присваиванием в
    теле класса (``post = get``), декоратора не имеет вовсе — нарушение.
    """
    tree = ast.parse(text)
    gate_names = _gate_decorator_names(tree)
    for cls in _view_classes(tree):
        for item in cls.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if item.name in _HANDLER_METHODS and not any(
                    _is_gate_decorator(d, gate_names) for d in item.decorator_list
                ):
                    yield item.lineno, f"{cls.name}.{item.name}"
            elif isinstance(item, ast.Assign):
                for target in item.targets:
                    if isinstance(target, ast.Name) and target.id in _HANDLER_METHODS:
                        yield item.lineno, f"{cls.name}.{target.id}"


class _Ref(str):
    """Значение гейта, заданное ИМЕНЕМ (константа модуля, параметр фабрики),
    а не литералом. Равно самому имени; ``isinstance`` отличает его от
    литерала с тем же текстом."""


_GATE_KW_RE = re.compile(
    r"(?<![\w.])(module|level)\s*=\s*(\"[^\"]*\"|'[^']*'|[A-Za-z_]\w*)")
_SPLAT_RE = re.compile(r"\*\*\s*[A-Za-z_]")


def _gate_of(block: str) -> dict:
    """``module``/``level`` вызова ``api_view(...)`` из ``_iter_api_view_calls``.

    Литерал — строкой без кавычек, имя — ``_Ref``; ключа нет — аргумент не
    передан. ``"**": True`` — в вызов что-то приходит распаковкой, и её
    содержимого текстовый разбор не видит.
    """
    gate: dict = {}
    for keyword, raw in _GATE_KW_RE.findall(block):
        gate.setdefault(keyword, raw[1:-1] if raw[0] in "\"'" else _Ref(raw))
    if _SPLAT_RE.search(block):
        gate["**"] = True
    return gate


_REQUIRED = object()


def _param_default(fn, name: str):
    """Умолчание параметра ``name`` у ``fn``: узел выражения; ``_REQUIRED`` —
    параметр обязательный; ``None`` — такого параметра нет."""
    args = fn.args
    positional = [*args.posonlyargs, *args.args]
    defaults = [None] * (len(positional) - len(args.defaults)) + list(args.defaults)
    pairs = [*zip(positional, defaults), *zip(args.kwonlyargs, args.kw_defaults)]
    for arg, default in pairs:
        if arg.arg == name:
            return _REQUIRED if default is None else default
    return None


def _literal(node, constants: dict[str, str]) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name) and node.id in constants:
        return constants[node.id]
    return None


def _level_problem(value: str) -> str | None:
    if value in _GATE_LEVELS:
        return None
    return f"level={value!r} — не {'/'.join(sorted(_GATE_LEVELS))}"


def _factory_call_offenders(tree, factory, param: str, constants, lines):
    """Вызовы фабрики ``factory`` в файле, передающие ей уровень не тем, что
    сторож может прочитать, или уровнем вне ``_GATE_LEVELS``. Вызов без
    уровня — не нарушение: тогда действует умолчание сигнатуры, проверенное
    вызывающим (а обязательный параметр Python без значения не пропустит)."""
    positional = [a.arg for a in (*factory.args.posonlyargs, *factory.args.args)]
    index = positional.index(param) if param in positional else None
    for call in ast.walk(tree):
        if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
                and call.func.id == factory.name):
            continue
        value = next((kw.value for kw in call.keywords if kw.arg == param), None)
        if value is None and index is not None and len(call.args) > index:
            value = call.args[index]
        if value is None:
            continue
        name = _qualified_name(lines, call.lineno, call.end_lineno) or factory.name
        literal = _literal(value, constants)
        if literal is None:
            yield call.lineno, name, f"{factory.name}(…{param}=?) — уровень не литерал"
        elif problem := _level_problem(literal):
            yield call.lineno, name, problem


def _level_offenders(text: str):
    """(lineno, имя, причина) для каждого гейта ``module=``, чей уровень не
    объявлен явно или не требует ничего (блок I.2, R7).

    Явно — это литерал рядом с ``module=``, константа модуля либо параметр
    объемлющей фабрики, чьё умолчание — литерал в её сигнатуре
    (``access/views.py::write(..., level: str = "write")``) или который
    обязателен; литералы, которые фабрике передают её вызовы, проверяются
    тоже. Нарушение — уровня нет вовсе (сработало бы умолчание самого
    ``api_view``), он приходит распаковкой ``**``, вычисляется или назван
    именем, которого сторож не может разрешить.
    """
    tree = ast.parse(text)
    lines = text.splitlines()
    constants = {
        target.id: node.value.value
        for node in tree.body
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
        for target in node.targets if isinstance(target, ast.Name)
    }
    functions = [node for node in ast.walk(tree)
                 if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
    checked_factories: set[str] = set()
    for start, end, block in _iter_api_view_calls(text):
        gate = _gate_of(block)
        if "module" not in gate:
            continue
        name = _qualified_name(lines, start, end) or "?"
        level = gate.get("level")
        if level is None:
            yield start, name, ("уровень приходит распаковкой ** — сторож его не видит"
                                if gate.get("**") else
                                "нет level= — сработало бы умолчание api_view")
            continue
        if not isinstance(level, _Ref):
            if problem := _level_problem(level):
                yield start, name, problem
            continue
        if level in constants:
            if problem := _level_problem(constants[level]):
                yield start, name, problem
            continue
        owners = [fn for fn in functions if fn.lineno <= start <= fn.end_lineno]
        factory = max(owners, key=lambda fn: fn.lineno, default=None)
        default = _param_default(factory, level) if factory else None
        if default is None:
            yield start, name, (f"level={level} — не константа модуля и не "
                                "параметр объемлющей фабрики")
            continue
        if default is not _REQUIRED:
            literal = _literal(default, constants)
            if literal is None:
                yield start, name, (f"умолчание {level} в сигнатуре {factory.name} "
                                    "— не литерал")
                continue
            if problem := _level_problem(literal):
                yield start, name, problem
                continue
        if factory.name not in checked_factories:
            checked_factories.add(factory.name)
            yield from _factory_call_offenders(tree, factory, level, constants, lines)


_CBV_SAMPLE = '''
from htqweb.http import ApiView, api_view

class SomeView(ApiView):
    @method_decorator(api_view(methods=("GET",), auth="jwt", module="hr", level="read"))
    def get(self, request):
        return {}

    def post(self, request):          # ← без декоратора: сторож обязан заметить
        return {}
'''


def test_guard_sees_a_cbv_method_without_a_decorator():
    found = {name for _lineno, name in _iter_undecorated_api_methods(_CBV_SAMPLE)}
    assert found == {"SomeView.post"}


_CBV_DERIVED_SAMPLE = '''
from htqweb.http import ApiView, api_view

read = method_decorator(api_view(methods=("GET",), auth="jwt", module="hr", level="read"))


def write(method):
    return method_decorator(api_view(methods=(method,), auth="jwt", module="hr", level="write"))


class DomainView(ApiView):
    def helper(self):
        return 1


class ItemView(DomainView):
    @read
    def get(self, request):
        return {}

    @write("POST")
    def post(self, request):
        return {}

    @method_decorator(csrf_exempt)
    def patch(self, request):
        return {}

    def delete(self, request):
        return {}


class LeafView(ItemView):
    async def put(self, request):
        return {}


class NotAView:
    def get(self):
        return 1
'''


def test_guard_follows_view_base_classes_declared_in_the_file():
    """Базовый класс домена (``DomainView(ApiView)``, как ``CompaniesView``/
    ``AccessView``) и его наследники любой глубины — тоже вьюхи; декоратор,
    не несущий ``api_view``, — не гейт; ``get`` у класса, не унаследованного
    от вьюхи, — не ручка."""
    found = {name for _lineno, name in _iter_undecorated_api_methods(_CBV_DERIVED_SAMPLE)}
    assert found == {"ItemView.patch", "ItemView.delete", "LeafView.put"}


_LEVELLESS_SAMPLE = '''
@api_view(methods=("GET",), auth="jwt", module="hr")
def some_handle(request):
    return {}
'''


def test_guard_requires_level_next_to_module():
    gates = [_gate_of(block) for _start, _end, block in _iter_api_view_calls(_LEVELLESS_SAMPLE)]
    assert gates and gates[0].get("module") == "hr"
    assert gates[0].get("level") is None
    assert [name for _lineno, name, _why in _level_offenders(_LEVELLESS_SAMPLE)] == ["some_handle"]


_FACTORY_SAMPLE = '''
MODULE = "hr"
LEVEL = "admin"


def implicit(method):
    return method_decorator(api_view(methods=(method,), auth="jwt", module=MODULE))


def signature_default(method, level: str = "write"):
    return method_decorator(api_view(methods=(method,), auth="jwt", module=MODULE,
                                     level=level))


def required(method, *, level):
    return method_decorator(api_view(methods=(method,), auth="jwt", module=MODULE,
                                     level=level))


def passthrough(method, **gate):
    return method_decorator(api_view(methods=(method,), auth="jwt", module=MODULE, **gate))


def unknown_name(method):
    return method_decorator(api_view(methods=(method,), auth="jwt", module=MODULE,
                                     level=somewhere))


def computed_default(method, level=pick_level()):
    return method_decorator(api_view(methods=(method,), auth="jwt", module=MODULE,
                                     level=level))


def constant(method):
    return method_decorator(api_view(methods=(method,), auth="jwt", module=MODULE,
                                     level=LEVEL))


def empty_gate(method):
    return method_decorator(api_view(methods=(method,), auth="jwt", module=MODULE,
                                     level="none"))


class ItemView(ApiView):
    @required("GET", level="read")
    def get(self, request):
        return {}

    @required("POST", level="full")
    def post(self, request):
        return {}
'''


def test_guard_reads_the_level_out_of_a_factory():
    """Фабрика засчитывается, только если уровень в ней объявлен явно:
    литералом, константой модуля или параметром, чьё умолчание — литерал в
    сигнатуре (либо обязательным параметром — тогда его литерал проверяется
    у каждого вызова фабрики). Уровень, который ``api_view`` взял бы по
    своему умолчанию, приехал через ``**`` или вычисляется, — нарушение;
    ``"none"`` и прочее вне ``read/write/admin`` — тоже (гейт, который
    ничего не требует)."""
    offenders = {name for _lineno, name, _why in _level_offenders(_FACTORY_SAMPLE)}
    assert offenders == {
        "implicit", "passthrough", "unknown_name", "computed_default",
        "empty_gate", "ItemView.post",
    }
