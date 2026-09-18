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

import pathlib
import re

import pytest
from django.test import RequestFactory

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
def test_gate_without_company_context_rejects():
    """Прав вне компании не бывает — подставлять «по умолчанию» запрещено."""
    resp = _view(module="hr", level="read")(_request(token()))
    assert resp.status_code == 403


# Аппки, чьи ручки и гейты авторизации разработаны вместе.
# Гейт на них не ретрофит на старые ручки — он часть исходного дизайна.
# Список должен быть КОРОТКИМ: каждая запись — это декларация, что у аппки
# нет старых ручек без авторизации, к которым гейт был приклеен потом.
_GATE_ALLOWLIST = {
    "apps/companies/views.py",  # новая аппка, ручки и гейт авторизации спроектированы вместе
}

# Четыре аппки блока I «Единая модель прав» — их судьбу решает
# apps.access.self_service (TRANSLATED_APPS/SELF_SERVICE), а не бланковый
# запрет ниже: задачи 4-7 вешают на них module=/level= по одной за коммит.
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
    не «нигде» — а «нигде за пределами четырёх аппок блока I и параллельной
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

    Три формы, которыми объявлена ручка в этих четырёх аппках:

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
    (``self``/``open``) не даёт добавить исключение молча — сторож требует
    ОДНУ из них у каждой записи, а не любую строку.
    """
    bad = [
        f"{app}.{name} = {reason!r}"
        for app, exempt in self_service.SELF_SERVICE.items()
        for name, reason in exempt.items()
        if reason not in self_service.REASONS
    ]
    assert not bad, f"недопустимая причина исключения (не self/open): {bad}"


def test_access_is_not_imported_at_module_level():
    """Вьюхи apps.access сами декорированы api_view — импорт наверху даст цикл."""
    import htqweb.http as http

    head = pathlib.Path(http.__file__).read_text(encoding="utf-8").splitlines()
    imports = [line for line in head if line.startswith(("import ", "from "))]
    assert not any("apps.access" in line for line in imports)
