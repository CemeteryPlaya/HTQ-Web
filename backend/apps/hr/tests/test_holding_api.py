"""HTTP-контракт ``GET /api/hr/v1/holding/headcount`` (блок H, задача 3).

Главное правило блока: сводка по всей группе видна ТОЛЬКО с поддомена
холдинга — даже когда у вызывающего есть настоящий доступ к домену ``hr``.
Обычная кадровая проверка (``hr_access.require_hr_access``) знает только
уровень доступа ВЫЗЫВАЮЩЕГО и ничего не знает про ВИД его компании, поэтому
вьюха обязана сверить это сама (``views._deny_unless_holding``) — тесты ниже
бьют именно по этому шву.

«HR-доступ» здесь — ``is_staff=True`` БЕЗ ``is_superuser`` (``token.is_elevated``
в ``hr_access.resolve_hr_access`` даёт полный HR-доступ без карточки
сотрудника). Это нарочно РАЗНЫЙ токен от платформенного администратора
(``is_superuser=True``): только последний обязан обходить проверку вида
компании — обычный кадровик, даже с полным HR-доступом, ограничен своим
поддоменом. Employee-карточками не пользуемся: они добавили бы отделы и
штат компаниям и испортили бы ручной подсчёт totals ниже.

Блок I, задача 6: ``holding_headcount`` встала под ``module="hr",
level="read"`` ПОВЕРХ ``hr_access.require_hr_access`` (без замены — обе
двери должны быть открыты разом). Токены здесь — сырой ``pyjwt.encode``
(не ``issue_token_pair``, см. ``token()``/``hr_token()``/``superuser_token()``
ниже), а не настоящие ``User`` строки, поэтому "полный HR-доступ"
``hr_token()`` больше НЕ покрывает новый гейт сам по себе —
``_grant_holding_role`` ниже даёт ``user_id`` токена узел ``hr`` через
``apps.access.tests.helpers.assign`` (НАПРЯМУЮ по ``user_id``, минуя
настоящую модель ``User`` — ``RoleAssignment.user_id`` обычный
``IntegerField``, без FK, см. ``apps/access/models.py``). Синтетическая
роль (не миграционно-засеянная ``hr-lead``) выбрана НАМЕРЕННО: тесты этого
файла помечены ``django_db(transaction=True)`` (нужны реальные, не
откатываемые DDL схем), а этот маркер заставляет pytest-django делать
``flush`` всей БД после КАЖДОГО теста — стирая и миграционно-засеянные
``access_role`` тоже (см. докстринг ``_grant_holding_role``).
``superuser_token()`` гейт обходит сам (``permissions_for`` короткое
замыкание на ``is_superuser``) — для него роль не нужна. ``token()`` (без
единой привилегии ни там, ни там) теперь получает 403 от ГЕЙТА раньше
``require_hr_access`` — единственный ассерт с изменённым текстом, см.
``test_no_hr_access_is_forbidden``.

Фикстура «две компании со схемами» — копия приёма
``apps.hr.tests.test_holding_summary::company_schemas`` (тесты соседних
файлов не делят фикстуры друг с другом), с одной содержательной поправкой:
здесь одна компания — ``CompanyKind.HOLDING`` (поддомен, откуда сводка обязана
открываться), другая — обычная дочерняя компания группы.

Токены и HTTP-хелперы — копия приёма ``apps/companies/tests/api_helpers.py``
(тоже не импорт: тесты соседней аппки не публичный контракт).
"""

from __future__ import annotations

from decimal import Decimal

import jwt as pyjwt
import pytest
from django.conf import settings
from django.db import connection
from django.test import Client

from apps.companies.models import Company, CompanyKind
from apps.companies.services import holding_views, migration_service, schema_service
from htqweb.tenancy.db import use_company

BASE = "/api/hr/v1/holding/headcount"

HOLDING_SLUG = "h-api-holding"
CHILD_SLUG = "h-api-child"
SLUGS = (HOLDING_SLUG, CHILD_SLUG)


# ── токены и запросы ──────────────────────────────────────────────────────

def token(**over) -> str:
    claims = {
        "user_id": 7, "username": "u", "email": "u@htq.test",
        "is_staff": False, "is_superuser": False, "is_admin": False,
        "token_type": "access", "iat": 1, "exp": 9_999_999_999,
        "iss": "htqweb-auth", "sub": "7",
        **over,
    }
    return pyjwt.encode(claims, settings.JWT_SECRET, algorithm="HS256")


def hr_token(**over) -> str:
    """``is_elevated`` (is_staff/is_admin), НЕ superuser — полный HR-доступ
    (``hr_access.resolve_hr_access``: ``token.is_elevated`` → wildcard), но
    без права обойти проверку вида компании."""
    return token(is_staff=True, is_admin=True, **over)


def superuser_token(**over) -> str:
    return token(user_id=9, sub="9", is_staff=True, is_superuser=True,
                is_admin=True, **over)


def auth(tok: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {tok}"}


def headers(slug: str, tok: str) -> dict:
    """Как ставит шлюз: слаг компании в заголовке + токен, выпущенный на неё."""
    return {"HTTP_X_HTQ_COMPANY": slug, **auth(tok)}


HR_TOKEN_USER_ID = 7  # см. token(): user_id по умолчанию


def _grant_holding_role(user_id: int, slug: str) -> None:
    """Задача 6 блока I: дать ``user_id`` узел ``hr`` (depth ``full``) в
    компании ``slug``, чтобы новый гейт ``module="hr", level="read"`` на
    ``holding_headcount`` пропускал ``hr_token()``.

    ``apps.access.tests.helpers.assign`` — НЕ засеянная миграцией роль
    (``hr-lead`` и т.п.): она заводит СВОЮ синтетическую роль через
    ``get_or_create`` при каждом вызове. Это принципиально для этого
    файла — тесты помечены ``django_db(transaction=True)`` (схемы компаний
    требуют реальных, не откатываемых DDL), а такой маркер заставляет
    pytest-django делать ``flush`` всей БД после КАЖДОГО теста, что стирает
    и мигационно-засеянные строки ``access_role`` (включая ``hr-lead``) —
    полагаться на них здесь нельзя, ссылка на уже несуществующую роль роняет
    следующий тест ``Role.DoesNotExist`` ещё до входа в тело теста, а его
    прерванный ``two_companies`` не успевает потом почистить схему,
    удваивая отказ на ``hr_department`` следующего теста. ``assign``
    создаёт роль каждый раз заново, поэтому переживает ``flush``."""
    from apps.access.tests.helpers import assign

    assign(slug, user_id, "hr", "view")


# ── фикстура схем ─────────────────────────────────────────────────────────

def _drop_holding_schema() -> None:
    with connection.cursor() as cur:
        cur.execute("DROP SCHEMA IF EXISTS holding CASCADE")


def _truncate_company_tables() -> None:
    """``transactional_db`` чистит только public — про схемы ``co_*`` он не
    знает, а они здесь общие на весь модуль."""
    for slug in SLUGS:
        with use_company(slug, include_public=False):
            with connection.cursor() as cur:
                cur.execute(
                    "TRUNCATE hr_employee, hr_staffingposition, "
                    "hr_position, hr_department CASCADE"
                )


@pytest.fixture(scope="module")
def company_schemas(django_db_setup, django_db_blocker):
    """Мигрированные схемы холдинга и дочерней компании, одни на весь модуль
    (полный прогон миграций тенантных аппок стоит около минуты — см. докстринг
    ``test_holding_summary.py::company_schemas``)."""
    with django_db_blocker.unblock():
        _drop_holding_schema()
        for slug in SLUGS:
            schema_service.drop_schema(slug)
        try:
            Company.objects.create(slug=HOLDING_SLUG, name="Holding QA",
                                   kind=CompanyKind.HOLDING)
            Company.objects.create(slug=CHILD_SLUG, name="Child QA",
                                   kind=CompanyKind.SERVICE)
            for slug in SLUGS:
                schema_service.create_schema(slug)
                migration_service.migrate_company(slug)
            Company.objects.filter(slug__in=SLUGS).delete()
            yield
        finally:
            _drop_holding_schema()
            for slug in SLUGS:
                schema_service.drop_schema(slug)
            Company.objects.filter(slug__in=SLUGS).delete()


def _seed_holding() -> None:
    """Один отдел, одна должность, один активный сотрудник и одна строка штата."""
    from apps.hr.models import Department, Employee, EmployeeStatus, Position, StaffingPosition

    with use_company(HOLDING_SLUG):
        dep = Department.objects.create(name="Головной офис", path="hq")
        pos = Position.objects.create(title="Директор", department=dep, weight=10)
        Employee.objects.create(
            first_name="Holding", last_name="Person", email="h@h-api-holding.test",
            department=dep, position=pos, hire_date="2024-01-01",
            status=EmployeeStatus.ACTIVE,
        )
        StaffingPosition.objects.create(
            position=pos, department=dep,
            headcount=Decimal("1.0"), salary=Decimal("200000.00"),
        )


def _seed_child() -> None:
    """Два отдела с активными сотрудниками и штатом — иные числа, чем у
    холдинга, чтобы сложение строк в тесте totals было содержательным."""
    from apps.hr.models import Department, Employee, EmployeeStatus, Position, StaffingPosition

    with use_company(CHILD_SLUG):
        dep = Department.objects.create(name="Производство", path="production")
        pos = Position.objects.create(title="Мастер", department=dep, weight=10)
        Employee.objects.create(
            first_name="Child", last_name="One", email="c1@h-api-child.test",
            department=dep, position=pos, hire_date="2024-01-01",
            status=EmployeeStatus.ACTIVE,
        )
        Employee.objects.create(
            first_name="Child", last_name="Two", email="c2@h-api-child.test",
            department=dep, position=pos, hire_date="2024-01-01",
            status=EmployeeStatus.ACTIVE,
        )
        StaffingPosition.objects.create(
            position=pos, department=dep,
            headcount=Decimal("3.0"), salary=Decimal("90000.00"),
        )


@pytest.fixture
def two_companies(db, company_schemas):
    """Холдинг + дочерняя компания, наполненные данными, со свежими вьюхами.

    Задача 6 блока I: + узел ``hr`` (``_grant_holding_role``) для
    ``HR_TOKEN_USER_ID`` в ОБЕИХ компаниях — ``hr_token()`` без него не
    проходит новый ``module="hr"`` гейт на ``holding_headcount`` ни с
    одного поддомена (в т.ч. дочернего, где решение всё равно выносит
    ``_deny_unless_holding`` — доступ нужен ЛИШЬ чтобы запрос дошёл до этой
    проверки, а не упёрся в гейт раньше)."""
    Company.objects.create(slug=HOLDING_SLUG, name="Holding QA", kind=CompanyKind.HOLDING)
    Company.objects.create(slug=CHILD_SLUG, name="Child QA", kind=CompanyKind.SERVICE)
    _seed_holding()
    _seed_child()
    holding_views.rebuild_holding_views()
    for slug in SLUGS:
        _grant_holding_role(HR_TOKEN_USER_ID, slug)
    try:
        yield
    finally:
        _drop_holding_schema()
        _truncate_company_tables()
        from apps.access.models import RoleAssignment
        RoleAssignment.objects.filter(company_slug__in=SLUGS, user_id=HR_TOKEN_USER_ID).delete()


@pytest.fixture
def client():
    return Client()


# ── auth: без токена ────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_requires_jwt_at_all(client):
    assert client.get(BASE).status_code == 401


# ── главное правило блока ───────────────────────────────────────────────────

@pytest.mark.django_db(transaction=True)
def test_holding_subdomain_with_hr_access_returns_200_with_companies(client, two_companies):
    resp = client.get(BASE, **headers(HOLDING_SLUG, hr_token(company=HOLDING_SLUG)))
    assert resp.status_code == 200
    body = resp.json()
    assert {row["company_slug"] for row in body["companies"]} == set(SLUGS)


@pytest.mark.django_db(transaction=True)
def test_child_subdomain_is_forbidden_even_with_hr_access(client, two_companies):
    """Главный тест блока: HR-доступ есть (тот же токен, что и выше), но
    поддомен — дочерней компании, а не холдинга. Обязан быть 403, а не 200."""
    resp = client.get(BASE, **headers(CHILD_SLUG, hr_token(company=CHILD_SLUG)))
    assert resp.status_code == 403


@pytest.mark.django_db(transaction=True)
def test_no_hr_access_is_forbidden(client, two_companies):
    """Обычный токен без единого HR-права (и, задача 6, без единой роли
    ``apps.access``) — 403 ещё до проверки вида компании, сводка сервиса
    вообще не вызывается. Detail теперь общий "Forbidden" от гейта
    ``module="hr"`` (который отказывает РАНЬШЕ ``require_hr_access`` —
    было "HR access required", тот же переход текста, что и в остальных
    файлах этой задачи)."""
    resp = client.get(BASE, **headers(HOLDING_SLUG, token(company=HOLDING_SLUG)))
    assert resp.status_code == 403


@pytest.mark.django_db(transaction=True)
def test_platform_admin_gets_200_from_child_subdomain(client, two_companies):
    """Платформенный администратор (``is_superuser``, не просто ``is_staff``)
    проходит всегда, даже с поддомена, с которого сводка обычному кадровику
    недоступна."""
    resp = client.get(BASE, **headers(CHILD_SLUG, superuser_token(company=CHILD_SLUG)))
    assert resp.status_code == 200
    body = resp.json()
    assert {row["company_slug"] for row in body["companies"]} == set(SLUGS)


# ── форма ответа ─────────────────────────────────────────────────────────

@pytest.mark.django_db(transaction=True)
def test_company_name_comes_from_the_registry(client, two_companies):
    resp = client.get(BASE, **headers(HOLDING_SLUG, hr_token(company=HOLDING_SLUG)))
    body = resp.json()
    names = {row["company_slug"]: row["company_name"] for row in body["companies"]}
    assert names[HOLDING_SLUG] == "Holding QA"
    assert names[CHILD_SLUG] == "Child QA"
    for name in names.values():
        assert name  # непусто — имена приезжают из реестра, а не только слаги


@pytest.mark.django_db(transaction=True)
def test_missing_registry_row_falls_back_to_slug_instead_of_500(client, two_companies, monkeypatch):
    """``get_company`` документированно отдаёт ``None``, если строки реестра
    уже нет — окно реальное: представления холдинга зафиксированы до
    следующей пересборки, а строка ``Company`` может исчезнуть раньше
    (осиротевшая строка после неудачного отката ``company_create``, см.
    CLAUDE.md), плюс 5-секундный TTL его кэша. Слепое индексирование
    ``get_company(slug)["name"]`` дало бы ``TypeError`` мимо единственного
    ``except`` — голый 500 без конверта ``{"detail": ...}``. Ручка обязана
    остаться 200: цифры по компании настоящие, отсутствует только вывеска."""
    from apps.companies import interface as companies_interface

    real_get_company = companies_interface.get_company

    def fake_get_company(slug):
        return None if slug == CHILD_SLUG else real_get_company(slug)

    monkeypatch.setattr(companies_interface, "get_company", fake_get_company)

    resp = client.get(BASE, **headers(HOLDING_SLUG, hr_token(company=HOLDING_SLUG)))
    assert resp.status_code == 200
    names = {row["company_slug"]: row["company_name"] for row in resp.json()["companies"]}
    assert names[CHILD_SLUG] == CHILD_SLUG       # вывеска пропала — остался слаг
    assert names[HOLDING_SLUG] == "Holding QA"   # у остальных строк имя как обычно


@pytest.mark.django_db(transaction=True)
def test_totals_equal_the_sum_of_the_rows(client, two_companies):
    """Числа посчитаны вручную по фикстуре, а не тем же выражением, что в
    сервисе: ``staffing_payroll_fund`` — ФОНД (``headcount * salary`` по
    строке), а не сумма окладов. holding — 1 активный/1.0 штат/
    1.0×200000.00=200000.00 ФОТ, child — 2 активных/3.0 штат/
    3.0×90000.00=270000.00 ФОТ. Совпадение holding-строки со старой формулой
    (``sum(salary)``) — совпадение именно ЭТОЙ строки (её headcount и есть
    1.0); child-строка (headcount=3.0) отличает формулы: 90000.00 против
    270000.00, поэтому итог по группе (470000.0) отличается от того, что
    дала бы старая формула (290000.0) — фикстура не вырождена."""
    resp = client.get(BASE, **headers(HOLDING_SLUG, hr_token(company=HOLDING_SLUG)))
    body = resp.json()

    rows = body["companies"]
    manual_totals = {
        "employees_active": sum(r["employees_active"] for r in rows),
        "employees_total": sum(r["employees_total"] for r in rows),
        "staffing_headcount": sum(r["staffing_headcount"] for r in rows),
        "staffing_payroll_fund": sum(r["staffing_payroll_fund"] for r in rows),
    }
    assert body["totals"] == manual_totals
    # Фикстура содержательна: не всё нулями.
    assert manual_totals["employees_active"] == 3
    assert manual_totals["staffing_headcount"] == 4.0
    assert manual_totals["staffing_payroll_fund"] == 470000.0


# ── представления снесены ────────────────────────────────────────────────

@pytest.mark.django_db(transaction=True)
def test_views_gone_returns_503_not_500_not_200_with_zeros(client, two_companies):
    holding_views.drop_holding_views()
    resp = client.get(BASE, **headers(HOLDING_SLUG, hr_token(company=HOLDING_SLUG)))
    assert resp.status_code == 503
    assert isinstance(resp.json()["detail"], str)


# ── оба написания пути (APPEND_SLASH=False) ─────────────────────────────────

@pytest.mark.django_db(transaction=True)
def test_both_path_spellings_respond(client, two_companies):
    tok = hr_token(company=HOLDING_SLUG)
    for path in (BASE, f"{BASE}/"):
        resp = client.get(path, **headers(HOLDING_SLUG, tok))
        assert resp.status_code != 404, path
