"""Задача 9 плана A: необязательный гейт ``module``/``level`` в ``api_view``.

Гейт ОБЪЯВЛЯЕТСЯ, но ни на одну существующую ручку в этой стадии не
навешивается — это отдельная работа поверх переработанного HR (спека A8).
Поэтому здесь он проверяется на собственных пробных вьюхах.
"""

import pytest
from django.test import RequestFactory

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


def test_gate_is_declared_but_not_hung_anywhere():
    """Гейт не навешивается ни на одну ручку, которая его не предусматривала.

    В этой стадии гейт объявлен, но ни на какую существующую ручку он не
    навешивается — это отдельная работа поверх переработанного HR (спека A8).
    Причина: модели доступа старых аппок (особенно HR) переделываются отдельно,
    и ретрофит гейта на них произойдёт в тот же момент — не раньше.

    Исключение: аппки вроде ``companies``, где ручки и гейты авторизации
    спроектированы и разработаны вместе с самого начала, уже в этой стадии.
    Для них гейт не ретрофит, а часть контракта.

    Список исключений (_GATE_ALLOWLIST) обязан быть коротким и содержать только
    аппки, где есть уверенность, что все существующие ручки правильно гейтированы.
    """
    import pathlib

    backend = pathlib.Path(__file__).resolve().parents[3]
    offenders = []
    for path in (backend / "apps").rglob("views.py"):
        posix_path = path.relative_to(backend).as_posix()
        if posix_path in _GATE_ALLOWLIST:
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "module=" in line and "api_view" in line:
                offenders.append(f"{posix_path}:{lineno}")
    assert offenders == [], f"гейт навешен раньше времени: {offenders}"


def test_access_is_not_imported_at_module_level():
    """Вьюхи apps.access сами декорированы api_view — импорт наверху даст цикл."""
    import pathlib

    import htqweb.http as http

    head = pathlib.Path(http.__file__).read_text(encoding="utf-8").splitlines()
    imports = [line for line in head if line.startswith(("import ", "from "))]
    assert not any("apps.access" in line for line in imports)
