"""Тесты сводки по людям и штату для домена hr (схема holding, блок H).

Фикстура «две компании со схемами и представлениями» собрана по образцу
``apps/companies/tests/test_holding_views.py::two_companies`` — своя, не
импортированная оттуда (см. бриф задачи 2). Тесты идут с
``transaction=True``: схемы и представления собираются DDL из нескольких
операторов подряд, и обычный ``atomic`` откатил бы часть шагов при падении
ассерта.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.db import ProgrammingError, connection

from apps.companies.models import Company, CompanyKind, CompanyStatus
from apps.companies.services import holding_views, migration_service, schema_service
from apps.hr.holding_models import HoldingContextRequired, HoldingEmployee
from apps.hr.services import holding_service
from apps.hr.services.holding_service import (
    HoldingViewsUnavailable, headcount_by_company,
)
from htqweb.tenancy.db import use_company

SLUGS = ("h-alpha", "h-beta")

REQUIRED_KEYS = {
    "company_slug", "employees_active", "employees_total",
    "departments_active", "positions_active",
    "staffing_headcount", "staffing_payroll_fund",
}


def _drop_holding_schema() -> None:
    with connection.cursor() as cur:
        cur.execute("DROP SCHEMA IF EXISTS holding CASCADE")


def _truncate_company_tables() -> None:
    """Убрать строки, которые тесты вставляют в схемы компаний.

    ``transactional_db`` чистит только public — про схемы ``co_*`` он не
    знает, а они здесь общие на весь модуль (см. company_schemas).
    """
    for slug in SLUGS:
        with use_company(slug, include_public=False):
            with connection.cursor() as cur:
                cur.execute(
                    "TRUNCATE hr_employee, hr_staffingposition, "
                    "hr_position, hr_department CASCADE"
                )


@pytest.fixture(scope="module")
def company_schemas(django_db_setup, django_db_blocker):
    """Мигрированные схемы двух компаний, одни на весь модуль.

    Полный прогон миграций тенантных аппок стоит около минуты — поэтому один
    раз на модуль, а не на каждый тест (см. докстринг companies-аналога).
    """
    with django_db_blocker.unblock():
        _drop_holding_schema()
        for slug in SLUGS:
            schema_service.drop_schema(slug)
        try:
            for slug in SLUGS:
                Company.objects.create(slug=slug, name=slug, kind=CompanyKind.SERVICE)
                schema_service.create_schema(slug)
                migration_service.migrate_company(slug)
            Company.objects.filter(slug__in=SLUGS).delete()
            yield
        finally:
            _drop_holding_schema()
            for slug in SLUGS:
                schema_service.drop_schema(slug)
            Company.objects.filter(slug__in=SLUGS).delete()


def _seed_alpha() -> None:
    """h-alpha: два активных, один уволенный, один мягко удалённый сотрудник.

    Плюс неактивные отдел и должность (не должны попасть в *_active), и две
    строки штатного расписания.
    """
    from apps.hr.models import Department, Employee, EmployeeStatus, Position, StaffingPosition

    with use_company("h-alpha"):
        active_department = Department.objects.create(name="Engineering", path="engineering")
        Department.objects.create(name="Legacy", path="legacy", is_active=False)
        active_position = Position.objects.create(
            title="Developer", department=active_department, weight=10,
        )
        Position.objects.create(
            title="Retired role", department=active_department,
            is_active=False, weight=20,
        )
        Employee.objects.create(
            first_name="Alice", last_name="Active", email="alice@h-alpha.test",
            department=active_department, position=active_position,
            hire_date="2024-01-01", status=EmployeeStatus.ACTIVE,
        )
        Employee.objects.create(
            first_name="Anna", last_name="Active2", email="anna@h-alpha.test",
            department=active_department, position=active_position,
            hire_date="2024-01-01", status=EmployeeStatus.ACTIVE,
        )
        Employee.objects.create(
            first_name="Tom", last_name="Terminated", email="tom@h-alpha.test",
            department=active_department, position=active_position,
            hire_date="2022-01-01", status=EmployeeStatus.TERMINATED,
        )
        Employee.objects.create(
            first_name="Ghost", last_name="Deleted", email="ghost@h-alpha.test",
            department=active_department, position=active_position,
            hire_date="2022-01-01", status=EmployeeStatus.ACTIVE, is_deleted=True,
        )
        StaffingPosition.objects.create(
            position=active_position, department=active_department,
            headcount=Decimal("2.5"), salary=Decimal("100000.00"),
        )
        StaffingPosition.objects.create(
            position=active_position, department=active_department,
            headcount=Decimal("1.0"), salary=Decimal("50000.50"),
        )


def _seed_beta() -> None:
    """h-beta: план (отдел, должность, штатная строка) есть, людей — нет.

    Именно этот случай проверяет test_a_company_without_people_still_appears_with_zeros:
    компания обязана остаться строкой сводки с нулями по людям, а не исчезнуть.
    """
    from apps.hr.models import Department, Position, StaffingPosition

    with use_company("h-beta"):
        department = Department.objects.create(name="Operations", path="operations")
        position = Position.objects.create(
            title="Manager", department=department, weight=10,
        )
        StaffingPosition.objects.create(
            position=position, department=department,
            headcount=Decimal("2"), salary=Decimal("60000"),
        )


@pytest.fixture
def two_companies(db, company_schemas):
    """Две действующие компании, наполненные данными, со свежими вьюхами."""
    for slug in SLUGS:
        Company.objects.create(slug=slug, name=slug, kind=CompanyKind.SERVICE)
    _seed_alpha()
    _seed_beta()
    holding_views.rebuild_holding_views()
    try:
        yield
    finally:
        _drop_holding_schema()
        _truncate_company_tables()


def _row(rows: list[dict], slug: str) -> dict:
    matches = [r for r in rows if r["company_slug"] == slug]
    assert len(matches) == 1, f"ожидалась ровно одна строка для {slug}, получено {matches}"
    return matches[0]


# ---------------------------------------------------------------------------
# Состав сводки
# ---------------------------------------------------------------------------

@pytest.mark.django_db(transaction=True)
def test_headcount_counts_every_active_company(two_companies):
    """В сводке ровно столько строк, сколько действующих компаний."""
    rows = headcount_by_company()
    assert {r["company_slug"] for r in rows} == set(SLUGS)
    assert len(rows) == len(SLUGS)


@pytest.mark.django_db(transaction=True)
def test_headcount_separates_active_from_total(two_companies):
    """Уволенный остаётся в таблице (status="terminated") и обязан попасть в
    total, но не в active — иначе численность группы раздувается на всех,
    кто когда-либо работал."""
    alpha = _row(headcount_by_company(), "h-alpha")
    assert alpha["employees_active"] == 2
    assert alpha["employees_total"] == 3


@pytest.mark.django_db(transaction=True)
def test_headcount_ignores_soft_deleted_employees(two_companies):
    """is_deleted — мягкое удаление; его не должно быть НИ в active, НИ в total."""
    alpha = _row(headcount_by_company(), "h-alpha")
    # 4 строки в таблице (2 активных + 1 уволенный + 1 удалённый), но total = 3.
    assert alpha["employees_total"] == 3
    assert alpha["employees_active"] == 2


@pytest.mark.django_db(transaction=True)
def test_staffing_is_reported_next_to_the_headcount(two_companies):
    """Штат против факта — первая цифра, которую спрашивает директор.

    ``staffing_payroll_fund`` — ФОНД оплаты труда: ``headcount * salary`` по
    КАЖДОЙ строке штатного расписания, просуммированный, а НЕ сумма
    окладов. Числа посчитаны вручную по фикстуре, а не тем же выражением,
    что в сервисе, и намеренно НЕ равны сумме окладов — иначе проверка не
    отличала бы верную формулу от `Sum("salary")`:
      * alpha: 2.5×100000.00 + 1.0×50000.50 = 250000.00 + 50000.50 =
        300000.50 (сумма окладов дала бы 150000.50 — другое число);
      * beta: 2×60000 = 120000.0 (сумма окладов дала бы 60000.0).
    """
    rows = headcount_by_company()
    alpha = _row(rows, "h-alpha")
    beta = _row(rows, "h-beta")
    assert alpha["staffing_headcount"] == 3.5                # 2.5 + 1.0
    assert alpha["staffing_payroll_fund"] == 300000.50        # 250000.00 + 50000.50
    assert beta["staffing_headcount"] == 2.0
    assert beta["staffing_payroll_fund"] == 120000.0          # 2 × 60000


@pytest.mark.django_db(transaction=True)
def test_keys_are_exactly_the_agreed_set(two_companies):
    """Точное сравнение множества ключей — контракт со схемой ручки."""
    for row in headcount_by_company():
        assert set(row.keys()) == REQUIRED_KEYS


@pytest.mark.django_db(transaction=True)
def test_numbers_are_plain_scalars(two_companies):
    """Decimal из БД обязан уехать наружу float'ом: JsonResponse Decimal не
    сериализует вовсе, а схема ручки объявляет float."""
    for row in headcount_by_company():
        assert isinstance(row["company_slug"], str)
        for key in ("employees_active", "employees_total",
                   "departments_active", "positions_active"):
            assert isinstance(row[key], int)
            assert not isinstance(row[key], bool)
        for key in ("staffing_headcount", "staffing_payroll_fund"):
            assert isinstance(row[key], float)
            assert not isinstance(row[key], Decimal)


@pytest.mark.django_db(transaction=True)
def test_a_company_without_people_still_appears_with_zeros(two_companies):
    """Компания без сотрудников — это НОЛЬ в сводке, а не пропущенная строка:
    иначе исчезнувшая компания выглядит как отсутствующая, а не как пустая."""
    beta = _row(headcount_by_company(), "h-beta")
    assert beta["employees_active"] == 0
    assert beta["employees_total"] == 0
    # У beta есть план (отдел/должность/штат) — сводка не занулила ЕГО тоже.
    assert beta["departments_active"] == 1
    assert beta["positions_active"] == 1
    assert beta["staffing_headcount"] == 2.0


@pytest.mark.django_db(transaction=True)
def test_headcount_excludes_inactive_departments_and_positions(two_companies):
    """Неактивные отдел/должность заведены в _seed_alpha именно для этого:
    фильтр ``is_active=True`` в сервисе обязан их не считать. Числа посчитаны
    вручную по фикстуре (2 отдела/2 должности заведено, по одному активно),
    а не тем же выражением, что в сервисе."""
    alpha = _row(headcount_by_company(), "h-alpha")
    assert alpha["departments_active"] == 1   # "Engineering", НЕ "Legacy"
    assert alpha["positions_active"] == 1     # "Developer", НЕ "Retired role"


@pytest.mark.django_db(transaction=True)
def test_a_company_whose_rows_all_fail_the_filters_stays_with_zeros(two_companies):
    """Строки ЕСТЬ, но ни одна не проходит фильтр активности — компания
    обязана остаться в сводке с нулями (приём — как
    ``apps.tasks.services.holding_service.projects_by_company``, см. тест
    ``apps.tasks.tests.test_holding_summary::test_a_company_whose_rows_all_fail_the_filters_stays_with_zeros``).

    Это не тот же случай, что ``h-beta`` (там сотрудников нет вовсе — план
    без факта), и держит он ровно одно решение сервиса: условия по
    ``is_active`` для отделов и должностей стоят внутри
    ``Count(filter=...)``, а НЕ в ``filter()`` выборки. Перенеси их обратно
    в ``filter()`` — и у h-alpha выборки отделов и должностей станут
    пустыми; сотрудники здесь намеренно тоже гашены ``is_deleted=True``
    (мягкое удаление отсекается выборкой САМОЙ по себе — это отдельное,
    верное поведение, не имеющее отношения к находке), а штатных строк нет
    вовсе — так ни одна из четырёх выборок не удержит слаг в объединении
    сама по себе, и проверка бьёт именно по фильтру департаментов/должностей,
    а не маскируется чужим источником слага. Если условие уедет в
    ``filter()``, компания, где законсервирована вся структура, ТИХО
    исчезнет со сводного экрана вместо того, чтобы показать там нули.
    Разница между «ноль» и «нет строки» — это разница между «всё
    заморожено» и «компании нет».
    """
    from apps.hr.models import Department, Employee, EmployeeStatus, Position, StaffingPosition

    with use_company("h-alpha"):
        Department.objects.update(is_active=False)
        Position.objects.update(is_active=False)
        Employee.objects.update(status=EmployeeStatus.TERMINATED, is_deleted=True)
        StaffingPosition.objects.all().delete()
        # Строки на месте (кроме штата, снесённого нарочно) — исчезать в
        # сводке нечему.
        assert Department.objects.count() == 2
        assert Position.objects.count() == 2
        assert Employee.objects.count() == 4
        assert StaffingPosition.objects.count() == 0

    rows = headcount_by_company()
    assert "h-alpha" in {r["company_slug"] for r in rows}, (
        "компания со строками, но без активных, ПРОПАЛА из сводки — "
        "статусное условие уехало из Count(filter=...) в filter() выборки"
    )
    alpha = _row(rows, "h-alpha")
    assert alpha["employees_active"] == 0
    assert alpha["employees_total"] == 0
    assert alpha["departments_active"] == 0
    assert alpha["positions_active"] == 0
    assert alpha["staffing_headcount"] == 0.0
    assert alpha["staffing_payroll_fund"] == 0.0


@pytest.mark.django_db(transaction=True)
def test_an_archived_company_disappears_from_the_summary(two_companies):
    """Архивную компанию rebuild_holding_views исключает из представлений —
    цифры группы обязаны это отражать."""
    Company.objects.filter(slug="h-beta").update(status=CompanyStatus.ARCHIVED)
    holding_views.rebuild_holding_views()
    rows = headcount_by_company()
    assert {r["company_slug"] for r in rows} == {"h-alpha"}


# ---------------------------------------------------------------------------
# Сторожа
# ---------------------------------------------------------------------------

def test_reader_refuses_to_work_outside_the_holding_context():
    """Главный сторож задачи: db_table читателя совпадает с таблицей
    компании, поэтому вызов без use_holding() прочитал бы ОДНУ компанию и
    выдал её цифры за групповые. Ожидается HoldingContextRequired."""
    with pytest.raises(HoldingContextRequired):
        HoldingEmployee.objects.exists()


def test_base_manager_also_refuses_to_work_outside_the_holding_context():
    """``_base_manager`` — то, чем пользуются refresh_from_db() и
    related-дескрипторы — обязан идти через тот же сторож, что и ``objects``.

    Без ``base_manager_name = "objects"`` в ``HoldingRow.Meta`` Django
    заводит ``_base_manager`` как голый ``models.Manager()`` (дефолт
    ``Options.base_manager``, если имя не задано явно), и он читал бы схему
    company-контекста мимо ``HoldingManager.get_queryset()`` — то есть мимо
    всей проверки, ради которой заведена эта задача.
    """
    with pytest.raises(HoldingContextRequired):
        HoldingEmployee._base_manager.exists()


@pytest.mark.django_db(transaction=True)
def test_summary_says_so_when_the_views_are_gone(two_companies):
    """Во время выкатки migrate_companies сносит представления. Читатель
    обязан поднять HoldingViewsUnavailable, а не вернуть нули и не упасть
    чем попало."""
    holding_views.drop_holding_views()
    with pytest.raises(HoldingViewsUnavailable):
        headcount_by_company()


@pytest.mark.django_db(transaction=True)
def test_headcount_reraises_programming_errors_unrelated_to_missing_views(
    two_companies, monkeypatch,
):
    """``_views_are_gone()`` уточняет причину ``ProgrammingError`` НАРОЧНО:
    докстринг сервиса обещает, что настоящая ошибка запроса не замаскируется
    под «идёт выкатка». Представления здесь на месте (rebuild уже отработал
    в фикстуре) — только это и делает проверку честной: если бы вьюх не
    было, любой ``ProgrammingError`` требовалось бы перехватывать как
    ``HoldingViewsUnavailable``, и тест был бы неотличим от подмены
    исключения."""

    def boom(queryset, **aggregates):
        raise ProgrammingError("syntax error at or near \"oops\"")

    monkeypatch.setattr(holding_service, "_by_company", boom)

    with pytest.raises(ProgrammingError, match="oops"):
        headcount_by_company()
