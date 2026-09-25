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
        # как словарь реестра из CompanyContextMiddleware
        # (companies.interface._serialize) — api_view читает is_active для
        # архивного режима.
        request.company = {"slug": company, "is_active": True}
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
    не «нигде» — а «нигде за пределами переведённых аппок и параллельной
    ветки signoff/contracts»: у первых (``self_service.TRANSLATED_APPS`` —
    пять аппок блока I и шесть блока L) своя, перевёрнутая проверка ниже
    (``test_gate_covers_every_handle_of_translated_apps``), у вторых
    (``_OUT_OF_SCOPE_APPS``) — работа другого разработчика, в которую этот
    файл не вмешивается. После блока L вне перевода остаётся только
    ``core`` — общий фундамент, а не модуль прав: ``module=`` на его ручке
    ловится здесь же, как и раньше.

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


def _coverage_offenders(texts: dict[str, str], exempt, label: str = "?"):
    """(missing, stale, unknown_exempt) сторожа полноты по модулям ОДНОЙ аппки.

    ``texts`` — путь модуля (для сообщения) → его исходник; ``exempt`` —
    ``self_service.SELF_SERVICE[app]``. Ручки собираются со ВСЕХ модулей, и
    ``unknown_exempt`` считается по их объединению: запись реестра находит
    свою ручку, в каком бы модуле аппки та ни лежала. ``label`` — имя аппки
    для сообщения о записи, не нашедшей ручки нигде.
    """
    missing: list[str] = []
    stale: list[str] = []
    seen: set[str] = set()
    for rel, text in texts.items():
        lines = text.splitlines()
        for start_lineno, end_lineno, block in _iter_api_view_calls(text):
            if "auth=None" in block:
                continue  # без JWT гейт module= структурно не выполнится (htqweb/http.py)
            name = _qualified_name(lines, start_lineno, end_lineno)
            if name:
                seen.add(name)
            location = f"{rel}:{start_lineno}" + (f" ({name})" if name else "")
            is_exempt = name in exempt
            has_gate = "module=" in block
            if is_exempt and has_gate:
                stale.append(location)
            elif not is_exempt and not has_gate:
                missing.append(location)
    unknown_exempt = [f"apps/{label}: {name}" for name in sorted(set(exempt) - seen)]
    return missing, stale, unknown_exempt


def test_gate_covers_every_handle_of_translated_apps():
    """Переведённая аппка: у каждой её ручки — ``module=``, кроме self_service.

    Читаются ВСЕ модули аппки (``_app_modules``: каждый ``.py`` кроме
    ``tests/`` и ``migrations/``), а не только ``views.py``: ручка
    ``api_view(auth="jwt")`` без ``module=`` в соседнем модуле (как
    ``apps/mail/webhooks.py``) иначе не попала бы ни в ``missing``, ни в
    реестр — сторож её просто не видел. Записи ``SELF_SERVICE`` сверяются с
    объединением ручек всех модулей аппки (ключ — голое имя ручки, без
    модуля; двух ручек с одним именем в разных модулях одной аппки сегодня
    нет).

    Падает в ОБЕ стороны:
    - ``missing`` — ручка без ``module=``, которой нет в ``SELF_SERVICE``:
      забытая ручка, ретрофит на неё не доехал;
    - ``stale`` — ручка есть в ``SELF_SERVICE``, но ``module=`` у неё
      всё-таки появился: либо список устарел (переименовали, гейт
      действительно нужен), либо гейт навешан по ошибке на то, что должно
      остаться открытым без единой роли;
    - ``unknown_exempt`` — запись ``SELF_SERVICE`` не находит соответствующей
      ручки ни в одном модуле аппки (переименовали функцию, либо, для
      class-based ручек ``access``, self-service-ручку не выделили в
      отдельный вызов ``api_view(...)`` — см. докстринг
      ``apps.access.self_service``).

    Ручки ``auth=None`` (вебхуки ``mail``, плеер записи и ``internal/*``
    ``conference``) не
    считаются: без JWT гейт модуля структурно не выполнится.

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
        texts = {path.relative_to(backend).as_posix(): path.read_text(encoding="utf-8")
                 for path in _app_modules(app)}
        app_missing, app_stale, app_unknown = _coverage_offenders(texts, exempt, app)
        missing += app_missing
        stale += app_stale
        unknown_exempt += app_unknown

    assert not missing, f"ручкам не хватает гейта модуля: {missing}"
    assert not stale, f"self_service устарел — гейт есть у объявленного самообслуживания: {stale}"
    assert not unknown_exempt, (
        "self_service ссылается на несуществующую ручку (переименовали "
        f"функцию, либо не выделили её в отдельный api_view(...)): {unknown_exempt}"
    )


_SIBLING_VIEWS_SAMPLE = '''
@api_view(methods=("GET",), auth="jwt", module="mail", level="read")
def inbox(request):
    return {}


@api_view(methods=("GET",), auth="jwt")
def my_settings(request):
    return {}
'''

_SIBLING_MODULE_SAMPLE = '''
@api_view(methods=("POST",), auth="jwt")
def push_hook(request):
    return {}
'''

_SIBLING_MODULE_OPEN_SAMPLE = '''
@api_view(methods=("POST",), auth=None)
def push_hook(request):
    return {}
'''


def test_coverage_guard_reads_sibling_modules():
    """Ручка без ``module=`` в соседнем модуле аппки (не ``views.py``) —
    нарушение; ``auth=None`` там же — нет; запись реестра находит ручку
    соседнего модуля (``unknown_exempt`` — по объединению модулей)."""
    missing, stale, unknown = _coverage_offenders(
        {"apps/x/views.py": _SIBLING_VIEWS_SAMPLE, "apps/x/webhooks.py": _SIBLING_MODULE_SAMPLE},
        {"my_settings": "self"}, "x")
    assert missing == ["apps/x/webhooks.py:2 (push_hook)"]
    assert stale == [] and unknown == []

    missing, stale, unknown = _coverage_offenders(
        {"apps/x/views.py": _SIBLING_VIEWS_SAMPLE, "apps/x/webhooks.py": _SIBLING_MODULE_OPEN_SAMPLE},
        {"my_settings": "self"}, "x")
    assert missing == [] and stale == [] and unknown == []

    missing, stale, unknown = _coverage_offenders(
        {"apps/x/views.py": _SIBLING_VIEWS_SAMPLE, "apps/x/webhooks.py": _SIBLING_MODULE_SAMPLE},
        {"my_settings": "self", "push_hook": "open"}, "x")
    assert missing == [] and stale == [] and unknown == []


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
        roots = _app_view_roots(app)
        exempt = self_service.SELF_SERVICE.get(app, {})
        for path in _app_modules(app):
            for lineno, name in _iter_undecorated_api_methods(
                    path.read_text(encoding="utf-8"), roots):
                if name not in exempt:
                    offenders.append(f"{path.relative_to(backend).as_posix()}:{lineno} ({name})")
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


def _view_classes(tree: ast.Module, extra_roots: frozenset[str] = frozenset()) -> list[ast.ClassDef]:
    """Классы файла, унаследованные (прямо или через другой класс файла) от
    корня ``_VIEW_ROOTS`` или от ``extra_roots`` — вьюх, объявленных в
    соседних модулях аппки. Имя, под которым корень импортирован
    (``from htqweb.http import ApiView as _Base``), — тоже корень."""
    classes = [node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
    known = set(_VIEW_ROOTS) | set(extra_roots)
    known |= {
        alias.asname
        for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
        for alias in node.names if alias.asname and alias.name in known
    }
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


def _roots_of_sources(sources: list[str]) -> frozenset[str]:
    """Имена классов-вьюх, объявленных в любом из исходников (модули одной
    аппки): база, объявленная в ``_base.py``, — корень и для ``views.py``."""
    trees = [ast.parse(text) for text in sources]
    names: set[str] = set()
    while True:
        found = {cls.name for tree in trees for cls in _view_classes(tree, frozenset(names))}
        if found <= names:
            return frozenset(names)
        names |= found


def _app_modules(app: str) -> list[pathlib.Path]:
    backend = pathlib.Path(__file__).resolve().parents[3]
    return [path for path in sorted((backend / "apps" / app).rglob("*.py"))
            if "tests" not in path.parts and "migrations" not in path.parts]


def _app_view_roots(app: str) -> frozenset[str]:
    return _roots_of_sources([p.read_text(encoding="utf-8") for p in _app_modules(app)])


def _iter_undecorated_api_methods(text: str, extra_roots: frozenset[str] = frozenset()):
    """(lineno, ``Класс.метод``) для каждой ручки класса-вьюхи без гейта-декоратора.

    Сторож полноты читает вызовы ``api_view(``; метод CBV без декоратора он
    не видел вовсе — то есть ручка без гейта (и без авторизации: ``ApiView``
    сам ``api_view`` не зовёт) была для него невидимой (блок I.2, R7).
    Ручка — метод из ``_HANDLER_METHODS`` в классе из ``_view_classes``.
    Декоратор засчитывается, только если несёт ``api_view``: сам вызов
    внутри или имя из ``_gate_decorator_names`` — ``@method_decorator(
    csrf_exempt)`` гейтом не считается. Ручка, заведённая присваиванием в
    теле класса (``post = get``), декоратора не имеет вовсе — нарушение.

    ``extra_roots`` — вьюхи из соседних модулей аппки (``_app_view_roots``).
    """
    tree = ast.parse(text)
    gate_names = _gate_decorator_names(tree)
    for cls in _view_classes(tree, extra_roots):
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
        if any(kw.arg is None for kw in call.keywords) or any(
                isinstance(arg, ast.Starred) for arg in call.args):
            yield (call.lineno,
                   _qualified_name(lines, call.lineno, call.end_lineno) or factory.name,
                   f"{factory.name}(…) получает аргументы распаковкой — уровень не прочитать")
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
        reassigned = next((
            node for node in ast.walk(factory)
            if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign))
            and any(isinstance(t, ast.Name) and t.id == level
                    for t in (node.targets if isinstance(node, ast.Assign) else [node.target]))
        ), None)
        if reassigned is not None:
            yield start, name, (f"{level} переприсваивается в теле {factory.name} "
                                f"(строка {reassigned.lineno}) — сторож видит только сигнатуру")
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


# ── Блок K: три известных обхода сторожа (roadmap §9.2) ────────────────────
#
# (а) база вьюхи под псевдонимом импорта (``ApiView as _Base``) или
#     объявленная в соседнем модуле аппки — ``_view_classes`` раньше
#     сравнивала только имя базы в том же файле;
# (б) ``level = "none"`` в теле фабрики после параметра и ``**{"level":
#     "none"}`` на вызове фабрики — раньше сторож видел лишь умолчание
#     сигнатуры и именованный аргумент;
# (в) функция-ручка без ``@api_view`` вовсе — сторож полноты идёт от
#     найденных вызовов ``api_view(`` и такую ручку не видит: список ручек
#     должен идти от ``urls.py``, а не от текста ``views.py``.


def _mentions_request_method(node: ast.AST) -> bool:
    """``True``, если где-то внутри выражения встречается ``request.method``
    (атрибут ``method`` у имени ``request``) — признак условия диспетчера,
    а не что оно означает буквально (``==``/``in``/``not in`` — любое)."""
    return any(
        isinstance(sub, ast.Attribute) and sub.attr == "method"
        and isinstance(sub.value, ast.Name) and sub.value.id == "request"
        for sub in ast.walk(node)
    )


def _rooted_in_request(node: ast.AST) -> bool:
    """``True``, если выражение — цепочка атрибутов/индексов/вызовов, в
    основании которой имя ``request`` (``request.method``,
    ``request.content_type.lower()``)."""
    while True:
        if isinstance(node, ast.Name):
            return node.id == "request"
        if isinstance(node, (ast.Attribute, ast.Subscript)):
            node = node.value
        elif isinstance(node, ast.Call):
            node = node.func
        else:
            return False


def _is_request_method_call(call: ast.Call) -> bool:
    """Вызов метода над выражением, укоренённым в ``request``
    (``request.method.upper()``, ``request.content_type.startswith(...)``),
    но не вызов самого ``request.<что-то>()`` верхнего уровня как функции
    чужого модуля: получатель метода обязан быть не голым ``request``."""
    func = call.func
    return (isinstance(func, ast.Attribute)
            and not isinstance(func.value, ast.Name)
            and _rooted_in_request(func.value))


def _is_plain_argument(node: ast.AST) -> bool:
    """Аргумент, который ничего не выполняет: имя или ``*имя``."""
    if isinstance(node, ast.Starred):
        node = node.value
    return isinstance(node, ast.Name)


def _is_405_or_gated_call(value: ast.AST, gated: set[str]) -> tuple[bool, str | None]:
    """``value`` — вызов гейтированной ручки того же файла либо ответ 405
    (``json_error(…, 405)`` или имя, содержащее ``method_not_allowed``).

    Аргументы вычисляются ДО входа в вызываемую функцию, то есть до гейта:
    у ответа 405 в них не бывает вызовов, у гейтированной ручки — только
    имена, ``*args``/``**kwargs`` и именованные аргументы с именем
    (``return _list(request, id=id)``). ``_list(request, wipe())`` — нарушение
    «вызов до гейта в диспетчере»."""
    if not isinstance(value, ast.Call):
        return False, "return — не вызов функции"
    name = _base_name(value.func)
    arguments = (*value.args, *(kw.value for kw in value.keywords))
    if any(isinstance(sub, ast.Call) for arg in arguments for sub in ast.walk(arg)):
        return False, (f"вызов до гейта в диспетчере: в аргументах "
                       f"return {name or '?'}(…) вызов — выполнится раньше гейта")
    if name and "method_not_allowed" in name:
        return True, None
    if name == "json_error" and any(
        isinstance(arg, ast.Constant) and arg.value == 405 for arg in arguments
    ):
        return True, None
    if name in gated:
        if not all(_is_plain_argument(arg) for arg in arguments):
            return False, (f"вызов до гейта в диспетчере: return {name}(…) — "
                           f"аргумент не имя, а выражение")
        return True, None
    return False, f"return {name or '?'}(…) — не гейтированная ручка того же файла и не 405"


def _dispatch_branch_ok(stmts: list, gated: set[str]) -> tuple[bool, str | None]:
    """Ветка диспетчера — РОВНО один ``return <вызов>``, ничего больше."""
    if len(stmts) != 1 or not isinstance(stmts[0], ast.Return) or stmts[0].value is None:
        return False, "ветка диспетчера — не единственный return вызова"
    return _is_405_or_gated_call(stmts[0].value, gated)


def _dispatch_if_ok(node: ast.If, gated: set[str]) -> tuple[bool, str | None]:
    """``if``, чьё условие упоминает ``request.method``, тело — один
    гейтированный/405 ``return``; ``elif`` — тот же разбор рекурсивно;
    голый ``else`` — та же проверка ветки, что и у ``if``.

    Условие вычисляется до гейта, поэтому вызовы в нём допустимы только
    как методы над выражением, укоренённым в ``request``
    (``request.method.upper()``); ``if request.method == "GET" and
    services.wipe():`` — нарушение «вызов до гейта в диспетчере»."""
    if not _mentions_request_method(node.test):
        return False, "условие if не про request.method"
    if any(isinstance(sub, ast.Call) and not _is_request_method_call(sub)
           for sub in ast.walk(node.test)):
        return False, "вызов до гейта в диспетчере: в условии if вызов не над request"
    ok, reason = _dispatch_branch_ok(node.body, gated)
    if not ok:
        return False, reason
    if not node.orelse:
        return True, None
    if len(node.orelse) == 1 and isinstance(node.orelse[0], ast.If):
        return _dispatch_if_ok(node.orelse[0], gated)
    return _dispatch_branch_ok(node.orelse, gated)


def _if_chain_is_exhaustive(node: ast.If) -> bool:
    """``True``, если ``if``/``elif``-цепочка заканчивается ``else`` (в т.ч.
    через вложенный ``elif``) — то есть закрывает ВСЕ пути, а не только
    условия, которые сама перечисляет. Пустой ``orelse`` — цепочка обрывается
    без покрытия остальных методов."""
    if not node.orelse:
        return False
    if len(node.orelse) == 1 and isinstance(node.orelse[0], ast.If):
        return _if_chain_is_exhaustive(node.orelse[0])
    return True


def _is_dispatcher(fn, gated: set[str]) -> tuple[bool, str | None]:
    """``fn`` — диспетчер по ``request.method``, если тело (после
    необязательного докстринга) состоит ТОЛЬКО из ``if``/``elif``/``else`` по
    ``request.method`` с однострочным гейтированным/405 ``return`` в каждой
    ветке и завершающего такого же ``return`` — он обязателен, если последняя
    цепочка ``if`` не закрыта ``else`` (иначе остальные методы ушли бы в
    неявный ``return None`` мимо гейта и 405). Любой другой оператор
    (присваивание, вызов сервиса, ``try``, …) — не диспетчер."""
    body = fn.body
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
            and isinstance(body[0].value.value, str):
        body = body[1:]
    if not body:
        return False, "не диспетчер: пустое тело"
    for index, stmt in enumerate(body):
        if isinstance(stmt, ast.If):
            ok, reason = _dispatch_if_ok(stmt, gated)
            if not ok:
                return False, reason
        elif index == len(body) - 1 and isinstance(stmt, ast.Return):
            ok, reason = _dispatch_branch_ok([stmt], gated)
            if not ok:
                return False, reason
        else:
            return False, ("не диспетчер: тело несёт не только if по "
                            "request.method и return")
    # Полнота: последний оператор тела обязан закрывать ВСЕ методы, а не
    # только совпавшие условия — иначе несовпавший метод проваливается в
    # неявный ``return None`` мимо гейта и 405. Оператор ``return`` на
    # верхнем уровне закрывает их безусловно (уже проверено выше); последний
    # ``if`` обязан завершаться ``else`` (в т.ч. через ``elif``-цепочку) —
    # каждая ветка которого, в свою очередь, уже проверена как ``return``
    # гейтированной ручки или 405 циклом выше.
    last = body[-1]
    if isinstance(last, ast.If) and not _if_chain_is_exhaustive(last):
        return False, "диспетчер не закрывает все методы: неявный return None"
    return True, None


def _module_functions(views_tree: ast.Module) -> tuple[dict, set[str]]:
    """Функции верхнего уровня модуля по имени и имена тех из них, что
    несут декоратор с ``api_view`` (напрямую или через фабрику файла)."""
    gate_names = _gate_decorator_names(views_tree)
    functions = {node.name: node for node in views_tree.body
                 if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    gated = {
        name for name, fn in functions.items()
        if any(_is_gate_decorator(d, gate_names) for d in fn.decorator_list)
    }
    return functions, gated


def _exempt_return_offenders(views_text: str, names):
    """(имя, причина) для функции из исключения
    ``_DISPATCHERS_WITH_OWN_LOGIC``, у которой хоть один ``return`` в теле
    (``ast.walk`` — на любой глубине ветвления) возвращает не вызов
    гейтированной функции того же файла и не 405 — по тем же правилам
    аргументов, что у строгого диспетчера. Исключение снимает только
    требование «ветвиться лишь по ``request.method``», а не проверку, куда
    ведут ветки: иначе новый ``return _purge(request)`` без гейта в
    исключённой ручке прошёл бы молча."""
    functions, gated = _module_functions(ast.parse(views_text))
    for name in sorted(names):
        fn = functions.get(name)
        if fn is None:
            continue
        for node in ast.walk(fn):
            if not isinstance(node, ast.Return):
                continue
            if node.value is None:
                yield name, (f"исключение: {name} возвращает не гейтированную "
                             f"ручку — голый return (строка {node.lineno})")
                continue
            ok, why = _is_405_or_gated_call(node.value, gated)
            if not ok:
                yield name, (f"исключение: {name} возвращает не гейтированную "
                             f"ручку — {why} (строка {node.lineno})")


def _url_view_offenders(urls_text: str, views_text: str,
                        siblings: dict[str, str] | None = None):
    """(имя, причина) для каждой вьюхи-функции из ``urls.py``, у которой нет
    декоратора с ``api_view`` и которая не читается как ДИСПЕТЧЕР по
    ``request.method`` (``_is_dispatcher``) — тело, состоящее только из
    ``if``/``elif``/``else`` по ``request.method``, где каждая ветка
    возвращает вызов гейтированной ручки того же файла либо ответ 405, а
    все пути закрыты (``else`` или завершающий ``return``); это
    легитимный, задокументированный в самом коде приём (один URL — несколько
    методов — раздельный гейтинг), а не дыра. Классы (``.as_view()``)
    проверяет сторож методов; ``include(...)`` — чужой список путей; всё,
    что не читается как ``views.<имя>`` или голое имя, — нарушение: молча
    пропущенная форма и была бы следующим слепым пятном.

    Имя, присвоенное на уровне модуля распаковкой из вызова фабрики того же
    файла (``a, b = _reference_endpoints(...)``), засчитывается, если тело
    ФАБРИКИ где-то зовёт ``api_view`` (``_calls_api_view``) — ВНУТРЕННИЕ
    диспетчеры самой фабрики этот разбор не проверяет отдельно, фабрика
    считается гейтированной целиком.
    """
    views_tree = ast.parse(views_text)
    functions, gated_functions = _module_functions(views_tree)
    factory_bound: set[str] = set()
    for node in views_tree.body:
        if not (isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Name)):
            continue
        factory = functions.get(node.value.func.id)
        if factory is None or not _calls_api_view(factory):
            continue
        for target in node.targets:
            names = target.elts if isinstance(target, (ast.Tuple, ast.List)) else [target]
            factory_bound.update(n.id for n in names if isinstance(n, ast.Name))
    for call in ast.walk(ast.parse(urls_text)):
        if not (isinstance(call, ast.Call) and _base_name(call.func) in {"path", "re_path"}):
            continue
        view = call.args[1] if len(call.args) > 1 else next(
            (kw.value for kw in call.keywords if kw.arg == "view"), None)
        if view is None:
            continue
        if isinstance(view, ast.Call) and _base_name(view.func) in {"as_view", "include"}:
            continue
        if (isinstance(view, ast.Attribute) and isinstance(view.value, ast.Name)
                and view.value.id in (siblings or {})):
            # Вьюха соседнего модуля аппки (``webhooks.gmail_push`` у mail,
            # блок L): обязана нести декоратор с ``api_view`` в СВОЁМ файле;
            # гейт или ``auth=None`` дальше — забота сторожей выше, не этого.
            _functions, sibling_gated = _module_functions(
                ast.parse(siblings[view.value.id]))
            if view.attr not in sibling_gated:
                yield ast.unparse(view), "функция соседнего модуля без api_view"
            continue
        if isinstance(view, ast.Attribute) and isinstance(view.value, ast.Name) \
                and view.value.id == "views":
            fn_name = view.attr
        elif isinstance(view, ast.Name):
            fn_name = view.id
        else:
            yield ast.unparse(view), "вьюха задана выражением, которое сторож не читает"
            continue
        if fn_name in factory_bound:
            continue
        fn = functions.get(fn_name)
        if fn is None:
            yield fn_name, "не найдена среди функций views.py"
            continue
        if fn_name in gated_functions:
            continue
        ok, reason = _is_dispatcher(fn, gated_functions)
        if not ok:
            yield fn_name, reason


#: Функции-ручки из ``urls.py``, которые разветвляются не только по
#: ``request.method`` и поэтому не проходят строгий признак диспетчера, но
#: чьи ветки ведут только в гейтированные ручки — проверено глазами, с
#: причиной. Запись, которую сторож больше не находит, — устарела и валит тест.
#: Исключение снимает только требование строгого диспетчера: каждый ``return``
#: такой функции сторож всё равно проверяет (``_exempt_return_offenders``).
_DISPATCHERS_WITH_OWN_LOGIC: dict[str, dict[str, str]] = {
    "hr": {
        "documents_collection": "POST разветвляется по Content-Type между "
                                "_upload_document_multipart и _upload_document "
                                "(обе под api_view)",
    },
}

#: Ручки из ``urls.py``, которые намеренно живут вне ``api_view`` целиком (не
#: диспетчеры): у каждой своя аутентификация и причина. Проверка ``return``
#: к ним не применяется — ветвления там нет; запись, которую сторож больше не
#: находит, устарела и валит тест.
_URL_VIEWS_OUTSIDE_API_VIEW: dict[str, dict[str, str]] = {
    "approvals": {
        "stream": "SSE: EventSource не шлёт заголовков — асинхронная вьюха, "
                  "JWT из ?token= вручную (services/sse.py), отдаёт только "
                  "свои события; вне блока L (спека §10)",
    },
}


def test_every_url_view_of_translated_apps_carries_api_view():
    """Функция-ручка ``hr``/``users``/``tasks`` вовсе без ``@api_view``
    невидима для сторожа полноты — у неё нет вызова ``api_view(``, который
    он читает. Список ручек даёт ``urls.py``: каждая зарегистрированная
    функция обязана нести декоратор с ``api_view`` (гейт или его отсутствие
    дальше проверяют сторожа выше и реестр самообслуживания).

    ``_DISPATCHERS_WITH_OWN_LOGIC`` — именной реестр ручек, которые
    разветвляются не только по ``request.method`` (строгий признак
    диспетчера, ``_is_dispatcher``, их не видит), но проверены глазами и
    ведут только в гейтированные функции. Запись оттуда, для которой сторож
    в этом прогоне не нашёл ни одной находки с тем же именем, — устарела
    (ручку переписали/удалили, а исключение забыли снять) и тоже нарушение,
    ровно тем же приёмом, что ``stale`` у ``self_service`` выше.

    Исключение не снимает проверку целиком: каждый ``return`` в теле
    исключённой функции обязан вернуть вызов гейтированной функции того же
    файла или 405 (``_exempt_return_offenders``)."""
    backend = pathlib.Path(__file__).resolve().parents[3]
    offenders = []
    for app in sorted(self_service.TRANSLATED_APPS):
        urls = backend / "apps" / app / "urls.py"
        views_text = (backend / "apps" / app / "views.py").read_text(encoding="utf-8")
        exempt = _DISPATCHERS_WITH_OWN_LOGIC.get(app, {})
        outside = _URL_VIEWS_OUTSIDE_API_VIEW.get(app, {})
        seen: set[str] = set()
        siblings = {path.stem: path.read_text(encoding="utf-8")
                    for path in (backend / "apps" / app).glob("*.py")
                    if path.stem not in {"views", "urls", "__init__"}}
        for name, why in _url_view_offenders(urls.read_text(encoding="utf-8"), views_text,
                                             siblings):
            seen.add(name)
            if name in exempt or name in outside:
                continue
            offenders.append(f"apps/{app}/urls.py: {name} — {why}")
        for name in sorted((set(exempt) | set(outside)) - seen):
            offenders.append(f"исключение устарело: {app}.{name}")
        for name, why in _exempt_return_offenders(views_text, set(exempt) & seen):
            offenders.append(f"apps/{app}/views.py: {why}")
    assert offenders == [], offenders


_ALIASED_BASE_SAMPLE = '''
from htqweb.http import ApiView as _Base

class SneakyView(_Base):
    def post(self, request):
        return {}
'''


def test_guard_resolves_an_aliased_view_base():
    found = {name for _lineno, name in _iter_undecorated_api_methods(_ALIASED_BASE_SAMPLE)}
    assert found == {"SneakyView.post"}


_BASE_MODULE_SAMPLE = '''
from htqweb.http import ApiView

class HrApiView(ApiView):
    pass
'''

_VIEWS_ON_FOREIGN_BASE_SAMPLE = '''
from ._base import HrApiView

class ItemView(HrApiView):
    def delete(self, request):
        return {}
'''


def test_guard_follows_a_view_base_from_a_sibling_module():
    roots = _roots_of_sources([_BASE_MODULE_SAMPLE, _VIEWS_ON_FOREIGN_BASE_SAMPLE])
    assert "HrApiView" in roots
    found = {name for _lineno, name in
             _iter_undecorated_api_methods(_VIEWS_ON_FOREIGN_BASE_SAMPLE, roots)}
    assert found == {"ItemView.delete"}


_REASSIGNED_LEVEL_SAMPLE = '''
MODULE = "hr"


def write(method, *, level="write"):
    level = "none"
    return method_decorator(api_view(methods=(method,), auth="jwt",
                                     module=MODULE, level=level))


def read(method, *, level="read"):
    return method_decorator(api_view(methods=(method,), auth="jwt",
                                     module=MODULE, level=level))


class ItemView(ApiView):
    @read("GET", **{"level": "none"})
    def get(self, request):
        return {}
'''


def test_guard_sees_a_level_hidden_in_the_factory():
    """Уровень, переприсвоенный в теле фабрики, и уровень, пришедший
    распаковкой на её вызове, сторож прочитать не может — нарушение."""
    offenders = {name for _lineno, name, _why in _level_offenders(_REASSIGNED_LEVEL_SAMPLE)}
    assert offenders == {"write", "ItemView.get"}


_URLS_SAMPLE = '''
from django.urls import path
from . import views

urlpatterns = [
    path("gated/", views.gated_handle),
    path("sneaky/", views.sneaky_handle),
    path("items/", views.ItemView.as_view()),
    path("odd/", make_view()),
    path("good/", views.good_dispatch),
    path("bad/", views.bad_dispatch),
    path("busy/", views.busy_dispatch),
    path("half/", views.half_dispatch),
    path("else/", views.else_dispatch),
    path("made-a/", views.made_a),
    path("made-b/", views.made_b),
    path("plain-a/", views.plain_a),
    path("upper/<int:id>/", views.upper_dispatch),
    path("argcall/", views.argcall_dispatch),
    path("testcall/", views.testcall_dispatch),
    path("own-ok/", views.own_logic_ok),
    path("own-bad/", views.own_logic_bad),
]
'''

_FUNCTION_VIEWS_SAMPLE = '''
@api_view(methods=("GET",), module="hr", level="read")
def gated_handle(request):
    return {}


def sneaky_handle(request):
    return {}


@api_view(methods=("GET",), module="hr", level="read")
def _list(request):
    return {}


@api_view(methods=("POST",), module="hr", level="write")
def _create(request):
    return {}


def _unauthorized(request):
    return {}


@csrf_exempt
def good_dispatch(request):
    """Диспетчер — декоратор, не несущий api_view (csrf_exempt), не мешает:
    признак диспетчера — тело, а не декораторы."""
    if request.method == "GET":
        return _list(request)
    if request.method == "POST":
        return _create(request)
    return json_error("Method Not Allowed", 405)


def bad_dispatch(request):
    if request.method == "GET":
        return _list(request)
    if request.method == "POST":
        return _unauthorized(request)
    return json_error("Method Not Allowed", 405)


def busy_dispatch(request):
    log_call(request)
    if request.method == "GET":
        return _list(request)
    return json_error("Method Not Allowed", 405)


def half_dispatch(request):
    """Единственный if без продолжения — остальные методы проваливаются в
    неявный return None мимо гейта и 405 (раунд 3: находка валидатора)."""
    if request.method == "GET":
        return _list(request)


def else_dispatch(request):
    if request.method == "GET":
        return _list(request)
    else:
        return json_error("Method Not Allowed", 405)


def upper_dispatch(request, id):
    """Метод над request в условии и имена в аргументах — допустимы."""
    if request.method.upper() == "GET":
        return _list(request, id=id)
    return json_error("Method Not Allowed", 405)


def argcall_dispatch(request):
    """Побочный эффект в аргументе выполнится до гейта (M1 финального ревью)."""
    if request.method == "GET":
        return _list(request, services.wipe_everything())
    return json_error("Method Not Allowed", 405)


def testcall_dispatch(request):
    """Побочный эффект в условии выполнится до гейта (M1 финального ревью)."""
    if request.method == "GET" and services.wipe_everything():
        return _list(request)
    return json_error("Method Not Allowed", 405)


def own_logic_ok(request):
    """Исключение: ветвится по Content-Type, но все return — гейт или 405."""
    if request.method == "POST":
        kind = (request.content_type or "").lower()
        if kind.startswith("multipart/"):
            return _create(request)
        return _list(request)
    return json_error("Method Not Allowed", 405)


def own_logic_bad(request):
    """Исключение, в которое дописали ручку без гейта (M3 финального ревью)."""
    if request.method == "POST":
        kind = (request.content_type or "").lower()
        if kind.startswith("multipart/"):
            return _unauthorized(request)
        return _create(request)
    return json_error("Method Not Allowed", 405)


def gated_factory(kind):
    @api_view(methods=("GET",), module="hr", level="read")
    def _inner_list(request):
        return {}

    def collection(request):
        return _inner_list(request)

    return collection, collection


made_a, made_b = gated_factory("kind")


def plain_factory():
    def collection(request):
        return {}

    return collection


plain_a = plain_factory()
'''


def test_guard_sees_a_url_view_without_api_view():
    problems = dict(_url_view_offenders(_URLS_SAMPLE, _FUNCTION_VIEWS_SAMPLE))
    assert set(problems) == {"sneaky_handle", "make_view()", "bad_dispatch", "busy_dispatch",
                             "half_dispatch", "plain_a", "argcall_dispatch",
                             "testcall_dispatch", "own_logic_ok", "own_logic_bad"}
    assert "вызов до гейта в диспетчере" in problems["argcall_dispatch"]
    assert "вызов до гейта в диспетчере" in problems["testcall_dispatch"]


def test_guard_checks_every_return_of_an_exempt_dispatcher():
    """Исключение ``_DISPATCHERS_WITH_OWN_LOGIC`` снимает только требование
    строгого диспетчера, а не проверку, куда ведут ветки (M3)."""
    found = list(_exempt_return_offenders(_FUNCTION_VIEWS_SAMPLE,
                                          {"own_logic_ok", "own_logic_bad"}))
    assert [name for name, _why in found] == ["own_logic_bad"]
    assert found[0][1].startswith("исключение: own_logic_bad возвращает не гейтированную ручку")


# ── Блок L: имя модуля и инвариант L1 ──────────────────────────────────────

from htqweb.middleware.service_gate import APP_LABEL_TO_SERVICE

#: Аппки блока L (каталог аппки → модуль прав). Проверяются, как только
#: аппка попала в TRANSLATED_APPS (задачи 4–9 плана блока L).
BLOCK_L_APPS = ("media_files", "conference", "messenger", "mail", "cms", "approvals")

#: Уровень employee-basic в модуле (спека блока L §4) — выписан руками.
EMPLOYEE_BASIC_LEVEL = {
    "media": "write", "conference": "read", "messenger": "write",
    "mail": "read", "cms": "read", "approvals": "write",
}

#: Ручки, бывшие admin=True до блока L (спека §6). Их уровень обязан быть
#: строго выше уровня employee-basic в модуле — иначе агрегат базовой роли
#: открыл бы их всем.
FORMER_ADMIN_HANDLES = {
    "media_files": {"list_files"},
    "messenger": {"admin_list_rooms", "admin_list_room_messages",
                  "admin_trigger_history_archive"},
    "mail": {"_list_mailboxes", "_create_mailbox", "_get_mailbox", "_update_mailbox",
             "_delete_mailbox", "reset_mailbox_password", "archive_mailbox",
             "restore_mailbox", "mailbox_status", "mailbox_lookup",
             "_get_mail_settings", "_put_mail_settings", "test_mail_connection",
             "mailbox_coverage", "_reconcile_report", "_reconcile_apply",
             "_list_aliases", "_create_alias", "delete_alias", "set_forwarding"},
    "cms": {"_list_contact_requests", "contact_request_stats", "_get_contact_request",
            "_update_contact_request", "_delete_contact_request", "reply_contact_request",
            "_create_news", "_update_news", "_delete_news", "translate_news",
            "_create_category", "_update_category", "_delete_category",
            "_create_tag", "_update_tag", "_delete_tag",
            "_list_home_sections_admin", "_create_home_section", "_delete_home_section",
            "_update_home_section", "home_sections_reorder", "home_items_collection",
            "home_items_reorder", "_update_home_item", "_delete_home_item"},
    "approvals": {"_create_project", "_delete_project", "create_source",
                  "update_source", "delete_source", "add_row", "delete_row",
                  # Общие разрезы статистики: admin=True пришёл из
                  # pre-production («кто сколько подал» по всей компании
                  # отвечал любому) уже после блока L — при слиянии встали
                  # под approvals:admin, как остальные бывшие admin=True.
                  "stats_overview", "stats_by_project", "stats_by_template",
                  "stats_by_actor", "stats_heatmap"},
}

_LEVEL_RANK = {"none": 0, "read": 1, "write": 2, "admin": 3}


def _module_of(app: str) -> str:
    return APP_LABEL_TO_SERVICE.get(app, app)


def _string_constants(text: str) -> dict[str, str]:
    tree = ast.parse(text)
    return {
        target.id: node.value.value
        for node in tree.body
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
        for target in node.targets if isinstance(target, ast.Name)
    }


def _gates(text: str):
    """(lineno, имя ручки, module, level) для каждого api_view с module=.

    module/level — литералы; имя-ссылка разрешается через строковые
    константы модуля, иначе остаётся ``None`` (сторож уровня выше это уже
    ловит)."""
    lines = text.splitlines()
    constants = _string_constants(text)
    for start, end, block in _iter_api_view_calls(text):
        gate = _gate_of(block)
        if "module" not in gate:
            continue
        module, level = gate["module"], gate.get("level")
        if isinstance(module, _Ref):
            module = constants.get(module)
        if isinstance(level, _Ref):
            level = constants.get(level)
        yield start, _qualified_name(lines, start, end) or "?", module, level


def _translated_block_l_apps():
    return [app for app in BLOCK_L_APPS if app in self_service.TRANSLATED_APPS]


def test_module_name_matches_the_app():
    """module= в аппке равен имени её модуля прав: у media_files это media,
    и module="media_files" молча дал бы уровень none всем."""
    offenders = []
    for app in sorted(self_service.TRANSLATED_APPS):
        expected = _module_of(app)
        for path in _app_modules(app):
            for lineno, name, module, _level in _gates(path.read_text(encoding="utf-8")):
                if module is not None and module != expected:
                    offenders.append(f"{path.name}:{lineno} {name}: module={module!r}, "
                                     f"ожидался {expected!r}")
    assert offenders == [], offenders


def test_employee_basic_passes_every_non_admin_handle():
    """Перенести как есть: ручка, не бывшая admin=True, пускает держателя
    одной employee-basic."""
    offenders = []
    for app in _translated_block_l_apps():
        basic = _LEVEL_RANK[EMPLOYEE_BASIC_LEVEL[_module_of(app)]]
        for path in _app_modules(app):
            for lineno, name, _module, level in _gates(path.read_text(encoding="utf-8")):
                if name in FORMER_ADMIN_HANDLES.get(app, set()) or level is None:
                    continue
                if _LEVEL_RANK[level] > basic:
                    offenders.append(f"{app}:{path.name}:{lineno} {name}: level={level}")
    assert offenders == [], offenders


def test_no_former_admin_handle_is_open_to_employee_basic():
    """Инвариант L1: бывшая admin=True требует уровень выше базовой роли."""
    offenders = []
    for app in _translated_block_l_apps():
        basic = _LEVEL_RANK[EMPLOYEE_BASIC_LEVEL[_module_of(app)]]
        seen = set()
        for path in _app_modules(app):
            for lineno, name, _module, level in _gates(path.read_text(encoding="utf-8")):
                if name not in FORMER_ADMIN_HANDLES.get(app, set()):
                    continue
                seen.add(name)
                if level is None or _LEVEL_RANK[level] <= basic:
                    offenders.append(f"{app}:{lineno} {name}: level={level}")
        missing = FORMER_ADMIN_HANDLES.get(app, set()) - seen
        offenders += [f"{app}: {name} — бывшая admin=True без гейта" for name in sorted(missing)]
    assert offenders == [], offenders


_WRONG_MODULE_SAMPLE = '''
@api_view(methods=("GET",), module="media_files", level="read")
def some_handle(request):
    return {}
'''


def test_guard_reads_the_module_of_a_gate():
    assert [(name, module) for _l, name, module, _lv in _gates(_WRONG_MODULE_SAMPLE)] \
        == [("some_handle", "media_files")]
