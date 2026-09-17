"""Тесты сводки по работам для домена tasks (схема holding, блок H).

Фикстура «две компании со схемами и представлениями» — копия приёма
``apps/hr/tests/test_holding_summary.py::company_schemas`` (тесты соседних
аппок не делят фикстуры друг с другом). Тесты идут с ``transaction=True``:
схемы и представления собираются DDL из нескольких операторов подряд, и
обычный ``atomic`` откатил бы часть шагов при падении ассерта.

Даты в фикстуре заданы ОТНОСИТЕЛЬНО ``timezone.localdate()``, а не
константами: платформа живёт в UTC, хост разработчика — нет, и на этом
расхождении в ``apps/tasks`` уже падают по ночам чужие тесты с
константными датами.
"""

from __future__ import annotations

import datetime

import pytest
from django.db import ProgrammingError, connection
from django.utils import timezone

from apps.companies.models import Company, CompanyKind, CompanyStatus
from apps.companies.services import holding_views, migration_service, schema_service
from apps.tasks.holding_models import HoldingContextRequired, HoldingTask
from apps.tasks.services import holding_service
from apps.tasks.services.holding_service import (
    HoldingViewsUnavailable, projects_by_company,
)
from htqweb.tenancy.db import use_company

SLUGS = ("t-alpha", "t-beta")

REQUIRED_KEYS = {
    "company_slug", "projects_active", "sites_active",
    "tasks_open", "tasks_overdue", "reports_last_date",
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
                    "TRUNCATE tasks_dailyreport, tasks_task, tasks_project, "
                    "tasks_site, tasks_workvolumetype CASCADE"
                )


@pytest.fixture(scope="module")
def company_schemas(django_db_setup, django_db_blocker):
    """Мигрированные схемы двух компаний, одни на весь модуль.

    Полный прогон миграций тенантных аппок стоит около минуты — поэтому один
    раз на модуль, а не на каждый тест (см. докстринг hr-аналога).
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


def _seed_alpha(today: datetime.date) -> None:
    """t-alpha: содержательная компания, все граничные случаи в одной.

    Проекты: 2 активных, 1 завершённый, 1 архивный → projects_active = 2.
    Объекты: 1 активный, 1 приостановленный, 1 закрытый → sites_active = 1.
    Задачи (сроки относительно ``today``):
      * T1 todo, срок вчера            → открыта, ПРОСРОЧЕНА;
      * T2 in_progress, срок сегодня   → открыта, не просрочена (граница);
      * T3 blocked, срока нет          → открыта, не просрочена;
      * T4 done, срок вчера            → ни открыта, ни просрочена;
      * T5 cancelled, срок вчера       → ни открыта, ни просрочена;
      * T6 todo, срок вчера, удалена   → ни открыта, ни просрочена;
      * T7 in_review, срок завтра      → открыта, не просрочена.
    → tasks_open = 4 (T1, T2, T3, T7), tasks_overdue = 1 (T1).
    Отчёты по T1: позавчера-1 и вчера живые, СЕГОДНЯШНИЙ — удалён →
    reports_last_date = вчера (удалённый отчёт не должен победить).
    """
    from apps.tasks.models import (
        DailyReport, Project, ProjectStatus, Site, SiteStatus, Status, Task,
        WorkVolumeType,
    )

    yesterday = today - datetime.timedelta(days=1)
    tomorrow = today + datetime.timedelta(days=1)

    with use_company("t-alpha"):
        Project.objects.create(name="Alpha Solar", status=ProjectStatus.ACTIVE)
        Project.objects.create(name="Alpha Wind", status=ProjectStatus.ACTIVE)
        Project.objects.create(name="Alpha Done", status=ProjectStatus.COMPLETED)
        Project.objects.create(name="Alpha Old", status=ProjectStatus.ARCHIVED)

        Site.objects.create(name="Алга", status=SiteStatus.ACTIVE)
        Site.objects.create(name="Сазаган", status=SiteStatus.SUSPENDED)
        Site.objects.create(name="Сданный", status=SiteStatus.CLOSED)

        t1 = Task.objects.create(key="TA-1", summary="T1", status=Status.TODO,
                                 due_date=yesterday)
        Task.objects.create(key="TA-2", summary="T2", status=Status.IN_PROGRESS,
                            due_date=today)
        Task.objects.create(key="TA-3", summary="T3", status=Status.BLOCKED,
                            due_date=None)
        Task.objects.create(key="TA-4", summary="T4", status=Status.DONE,
                            due_date=yesterday)
        Task.objects.create(key="TA-5", summary="T5", status=Status.CANCELLED,
                            due_date=yesterday)
        Task.objects.create(key="TA-6", summary="T6", status=Status.TODO,
                            due_date=yesterday, is_deleted=True)
        Task.objects.create(key="TA-7", summary="T7", status=Status.IN_REVIEW,
                            due_date=tomorrow)

        valy = WorkVolumeType.objects.create(slug="valy", name="Валы")
        DailyReport.objects.create(
            task=t1, volume_type=valy, quantity=10,
            work_date=today - datetime.timedelta(days=3))
        DailyReport.objects.create(
            task=t1, volume_type=valy, quantity=20, work_date=yesterday)
        DailyReport.objects.create(
            task=t1, volume_type=valy, quantity=30, work_date=today,
            is_deleted=True)


def _seed_beta() -> None:
    """t-beta: один активный проект и больше ничего.

    Именно этот случай проверяет test_a_company_without_tasks_still_appears_with_zeros:
    компания обязана остаться строкой сводки с нулями по задачам и
    ``reports_last_date=None``, а не исчезнуть и не показать сегодняшнюю дату.
    """
    from apps.tasks.models import Project, ProjectStatus

    with use_company("t-beta"):
        Project.objects.create(name="Beta Only", status=ProjectStatus.ACTIVE)


@pytest.fixture
def today() -> datetime.date:
    return timezone.localdate()


@pytest.fixture
def two_companies(db, company_schemas, today):
    """Две действующие компании, наполненные данными, со свежими вьюхами."""
    for slug in SLUGS:
        Company.objects.create(slug=slug, name=slug, kind=CompanyKind.SERVICE)
    _seed_alpha(today)
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
def test_summary_counts_every_active_company(two_companies):
    """В сводке ровно столько строк, сколько действующих компаний."""
    rows = projects_by_company()
    assert {r["company_slug"] for r in rows} == set(SLUGS)
    assert len(rows) == len(SLUGS)


@pytest.mark.django_db(transaction=True)
def test_projects_active_counts_only_active_status(two_companies):
    """Завершённый и архивный проекты заведены в _seed_alpha именно для
    этого: из четырёх проектов активных два. Число посчитано вручную по
    фикстуре, а не тем же выражением, что в сервисе."""
    alpha = _row(projects_by_company(), "t-alpha")
    assert alpha["projects_active"] == 2


@pytest.mark.django_db(transaction=True)
def test_sites_active_counts_only_active_status(two_companies):
    """Приостановленный и закрытый объекты — не «активные»: из трёх один."""
    alpha = _row(projects_by_company(), "t-alpha")
    assert alpha["sites_active"] == 1


@pytest.mark.django_db(transaction=True)
def test_tasks_open_excludes_terminal_and_deleted(two_companies):
    """Семь задач в таблице; done, cancelled и мягко удалённая — не
    открытые. Остаются T1, T2, T3, T7."""
    alpha = _row(projects_by_company(), "t-alpha")
    assert alpha["tasks_open"] == 4


@pytest.mark.django_db(transaction=True)
def test_done_task_is_neither_open_nor_overdue(two_companies):
    """T4 (done, срок вчера) и T5 (cancelled, срок вчера) не попадают ни в
    open, ни в overdue: просрочка — это «срок прошёл, а работа НЕ закрыта».
    Одна просроченная — T1; было бы 3, если бы терминальные считались."""
    alpha = _row(projects_by_company(), "t-alpha")
    assert alpha["tasks_overdue"] == 1
    assert alpha["tasks_open"] == 4


@pytest.mark.django_db(transaction=True)
def test_overdue_boundary_is_yesterday_not_today(two_companies):
    """Граница: срок вчера — просрочена (T1), срок сегодня — нет (T2).
    Если бы условие было ``due_date <= today``, overdue дал бы 2."""
    alpha = _row(projects_by_company(), "t-alpha")
    assert alpha["tasks_overdue"] == 1


@pytest.mark.django_db(transaction=True)
def test_task_without_due_date_is_not_overdue(two_companies):
    """T3 без срока — открыта, но просроченной быть не может.

    Сценарий собран заново: T3 остаётся единственной задачей компании, чтобы
    ноль в overdue не получился «за компанию» с другими задачами фикстуры.
    Представления — живой UNION ALL по таблицам, пересобирать их после
    удаления строк не нужно."""
    from apps.tasks.models import Task

    with use_company("t-alpha"):
        Task.objects.exclude(key="TA-3").delete()
    alpha = _row(projects_by_company(), "t-alpha")
    assert alpha["tasks_open"] == 1
    assert alpha["tasks_overdue"] == 0


@pytest.mark.django_db(transaction=True)
def test_reports_last_date_ignores_deleted_reports(two_companies, today):
    """Самый свежий отчёт — сегодняшний, но он удалён; сводка обязана
    показать вчерашний. Иначе исправленная отчётность выглядела бы как
    свежая."""
    alpha = _row(projects_by_company(), "t-alpha")
    assert alpha["reports_last_date"] == today - datetime.timedelta(days=1)


@pytest.mark.django_db(transaction=True)
def test_a_company_without_reports_gives_none_not_today(two_companies, today):
    """Компания без единого отчёта — ``None``, а не сегодняшняя дата и не
    ноль: «не отчитывались никогда» и «отчитались сегодня» обязаны
    различаться на экране директора."""
    beta = _row(projects_by_company(), "t-beta")
    assert beta["reports_last_date"] is None
    assert beta["reports_last_date"] != today


@pytest.mark.django_db(transaction=True)
def test_a_company_without_tasks_still_appears_with_zeros(two_companies):
    """Компания без задач и объектов — это НОЛЬ в сводке, а не пропущенная
    строка: иначе исчезнувшая компания выглядит как отсутствующая, а не
    как пустая."""
    beta = _row(projects_by_company(), "t-beta")
    assert beta["sites_active"] == 0
    assert beta["tasks_open"] == 0
    assert beta["tasks_overdue"] == 0
    # У beta есть проект — сводка не занулила ЕГО тоже.
    assert beta["projects_active"] == 1


@pytest.mark.django_db(transaction=True)
def test_keys_are_exactly_the_agreed_set(two_companies):
    """Точное сравнение множества ключей — контракт со схемой ручки."""
    for row in projects_by_company():
        assert set(row.keys()) == REQUIRED_KEYS


@pytest.mark.django_db(transaction=True)
def test_numbers_are_plain_scalars(two_companies):
    """Счётчики — int (не bool, не Decimal), дата — ``datetime.date`` или
    ``None``: схема ручки объявляет ``int`` и ``date | None``."""
    for row in projects_by_company():
        assert isinstance(row["company_slug"], str)
        for key in ("projects_active", "sites_active", "tasks_open", "tasks_overdue"):
            assert isinstance(row[key], int), key
            assert not isinstance(row[key], bool), key
        assert row["reports_last_date"] is None or isinstance(
            row["reports_last_date"], datetime.date)


@pytest.mark.django_db(transaction=True)
def test_an_archived_company_disappears_from_the_summary(two_companies):
    """Архивную компанию rebuild_holding_views исключает из представлений —
    цифры группы обязаны это отражать."""
    Company.objects.filter(slug="t-beta").update(status=CompanyStatus.ARCHIVED)
    holding_views.rebuild_holding_views()
    rows = projects_by_company()
    assert {r["company_slug"] for r in rows} == {"t-alpha"}


# ---------------------------------------------------------------------------
# Сторожа
# ---------------------------------------------------------------------------

def test_reader_refuses_to_work_outside_the_holding_context():
    """Главный сторож задачи: db_table читателя совпадает с таблицей
    компании, поэтому вызов без use_holding() прочитал бы ОДНУ компанию и
    выдал её цифры за групповые. Ожидается HoldingContextRequired."""
    with pytest.raises(HoldingContextRequired):
        HoldingTask.objects.exists()


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
        HoldingTask._base_manager.exists()


@pytest.mark.django_db(transaction=True)
def test_summary_says_so_when_the_views_are_gone(two_companies):
    """Во время выкатки migrate_companies сносит представления. Читатель
    обязан поднять HoldingViewsUnavailable, а не вернуть нули и не упасть
    чем попало."""
    holding_views.drop_holding_views()
    with pytest.raises(HoldingViewsUnavailable):
        projects_by_company()


@pytest.mark.django_db(transaction=True)
def test_summary_reraises_programming_errors_unrelated_to_missing_views(
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
        projects_by_company()
