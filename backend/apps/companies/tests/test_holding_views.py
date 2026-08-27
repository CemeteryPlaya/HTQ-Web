"""Сводные UNION ALL-представления схемы holding.

Тесты, которые действительно строят представления, идут с
``transaction=True``: CREATE VIEW — это DDL из нескольких операторов подряд,
и обёрнутый в atomic тест откатил бы половину сделанного между шагами. Платой
за это является ручная уборка — за таким тестом никто ничего не откатывает,
поэтому teardown фикстуры обязателен и обязан отрабатывать в том числе на
пути упавшего ассерта (``try/finally``).

Порядок уборки не произволен: ``DROP SCHEMA co_... CASCADE`` утащил бы за
собой зависящие от неё представления схемы holding, и следующий тест получил
бы holding в состоянии, которое никто не задавал. Поэтому сначала сносится
holding целиком, и только потом схемы компаний.

Схемы компаний создаются и мигрируются ОДИН раз на модуль, а не на каждый
тест: полный прогон миграций тенантных аппок на две компании стоит около
минуты, а сами тесты его результат не портят. Строки реестра при этом
заводятся на каждый тест — ``transactional_db`` вычищает public между
тестами, а схемы ``co_*`` не трогает, потому что не знает о них.
"""

import pytest
from django.db import connection

from apps.companies.models import Company, CompanyKind, CompanyStatus
from apps.companies.services import holding_views, migration_service, schema_service

SLUGS = ("t-alpha", "t-beta")


def _drop_holding_schema() -> None:
    with connection.cursor() as cur:
        cur.execute("DROP SCHEMA IF EXISTS holding CASCADE")


def _view_columns(name: str) -> list[str]:
    with connection.cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'holding' AND table_name = %s "
            "ORDER BY ordinal_position",
            [name],
        )
        return [row[0] for row in cur.fetchall()]


def _view_names() -> set[str]:
    with connection.cursor() as cur:
        cur.execute(
            "SELECT table_name FROM information_schema.views "
            "WHERE table_schema = 'holding'"
        )
        return {row[0] for row in cur.fetchall()}


def _viewdef(name: str) -> str:
    with connection.cursor() as cur:
        cur.execute("SELECT pg_get_viewdef(%s::regclass, true)", [f"holding.{name}"])
        return cur.fetchone()[0]


@pytest.fixture(scope="module")
def company_schemas(django_db_setup, django_db_blocker):
    """Мигрированные схемы двух компаний, одни на весь модуль.

    ``django_db_blocker.unblock()`` обязателен: фикстура работает вне теста,
    где pytest-django держит доступ к БД закрытым.
    """
    with django_db_blocker.unblock():
        _drop_holding_schema()
        # Уборка на входе, а не только на выходе: схема, оставшаяся от
        # прогона, который упал до teardown, иначе делала бы следующий
        # прогон зелёным по чужим таблицам.
        for slug in SLUGS:
            schema_service.drop_schema(slug)
        try:
            for slug in SLUGS:
                # migrate_company пишет CompanySchemaVersion, поэтому строка
                # реестра нужна уже здесь; тесты заведут свои поверх.
                Company.objects.create(slug=slug, name=slug,
                                       kind=CompanyKind.SERVICE)
                schema_service.create_schema(slug)
                migration_service.migrate_company(slug)
            Company.objects.filter(slug__in=SLUGS).delete()
            yield
        finally:
            _drop_holding_schema()
            for slug in SLUGS:
                schema_service.drop_schema(slug)
            Company.objects.filter(slug__in=SLUGS).delete()


@pytest.fixture
def two_companies(db, company_schemas):
    """Две действующие компании в реестре поверх готовых схем."""
    for slug in SLUGS:
        Company.objects.create(slug=slug, name=slug, kind=CompanyKind.SERVICE)
    try:
        yield
    finally:
        _drop_holding_schema()
        _truncate_company_tables()


def _truncate_company_tables() -> None:
    """Убрать строки, которые тесты вставляют в схемы компаний.

    ``transactional_db`` вычищает только public: про схемы ``co_*`` он не
    знает, и вставленное одним тестом дожило бы до следующего, а схемы здесь
    общие на весь модуль. Чистится ровно то, куда пишут тесты
    (``hr_department`` и всё, что на него ссылается) — не «всё подряд»:
    список тенантных таблиц в тесте пришлось бы поддерживать руками, и он
    разъезжался бы с миграциями молча.
    """
    from htqweb.tenancy.db import use_company

    for slug in SLUGS:
        with use_company(slug):
            with connection.cursor() as cur:
                cur.execute("TRUNCATE hr_department CASCADE")


def test_holding_models_covers_every_tenant_app():
    """Имена из apps/<домен>/holding.py резолвятся в настоящие модели.

    Опечатка в HOLDING_MODELS иначе всплыла бы только LookupError'ом внутри
    пересборки — то есть в момент заведения компании, а не в тестах.
    """
    labels = {model._meta.app_label for model in holding_views.holding_models()}
    assert labels == {"hr", "tasks", "contracts", "signoff"}


def test_holding_module_without_declaration_is_an_error(monkeypatch):
    """holding.py без HOLDING_MODELS — опечатка, а не «нечего сводить».

    Молчаливый пропуск убрал бы из сводок целую аппку: цифры стали бы
    неверными, а не отсутствующими.
    """
    import apps.signoff.holding as module

    monkeypatch.delattr(module, "HOLDING_MODELS")
    with pytest.raises(AttributeError, match="HOLDING_MODELS"):
        holding_views.holding_models()


@pytest.mark.django_db(transaction=True)
def test_rebuild_creates_view_with_company_column(two_companies):
    holding_views.rebuild_holding_views()
    columns = _view_columns("tasks_task")
    assert columns[0] == "company_slug"
    assert "id" in columns


@pytest.mark.django_db(transaction=True)
def test_rebuild_creates_a_view_per_declared_model(two_companies):
    created = holding_views.rebuild_holding_views()
    expected = {model._meta.db_table for model in holding_views.holding_models()}
    assert set(created) == expected
    assert _view_names() == expected


@pytest.mark.django_db(transaction=True)
def test_view_unions_all_active_companies(two_companies):
    holding_views.rebuild_holding_views()
    with connection.cursor() as cur:
        cur.execute("SELECT DISTINCT company_slug FROM holding.tasks_task")
        # Таблицы пусты, но план запроса обязан быть валидным по обеим веткам.
        assert cur.fetchall() == []
    definition = _viewdef("tasks_task")
    assert "co_t_alpha" in definition
    assert "co_t_beta" in definition


@pytest.mark.django_db(transaction=True)
def test_view_reads_rows_from_every_company_schema(two_companies):
    """Ветки не перечислены, а реально читаются — и колонки в них совпадают.

    Проверка «DISTINCT вернул пусто» прошла бы и на вьюхе с одной веткой.
    А перепутанный порядок колонок между ветками дал бы валидное
    представление с подменёнными значениями — здесь это видно по тому, что
    name и path не поменялись местами ни в одной из компаний.
    """
    from htqweb.tenancy.db import use_company

    holding_views.rebuild_holding_views()
    for slug in SLUGS:
        with use_company(slug):
            with connection.cursor() as cur:
                cur.execute(
                    "INSERT INTO hr_department (name, path) VALUES (%s, %s)",
                    [f"name-{slug}", f"path-{slug}"],
                )
    with connection.cursor() as cur:
        cur.execute(
            "SELECT company_slug, name, path FROM holding.hr_department "
            "ORDER BY company_slug"
        )
        assert cur.fetchall() == [
            ("t-alpha", "name-t-alpha", "path-t-alpha"),
            ("t-beta", "name-t-beta", "path-t-beta"),
        ]


@pytest.mark.django_db(transaction=True)
def test_archived_company_drops_out_of_view(two_companies):
    holding_views.rebuild_holding_views()
    Company.objects.filter(slug="t-beta").update(status=CompanyStatus.ARCHIVED)
    holding_views.rebuild_holding_views()
    definition = _viewdef("tasks_task")
    assert "co_t_alpha" in definition
    assert "co_t_beta" not in definition


@pytest.mark.django_db(transaction=True)
def test_rebuild_uses_a_fresh_company_list(two_companies):
    """Пересборка не имеет права читать пятисекундный кэш реестра.

    Она идёт сразу за созданием или архивацией компании: кэшированный список
    отдал бы состав БЕЗ неё, и компания молча выпала бы из сводок — без
    ошибки и без следа в логе. Здесь кэш прогревается заведомо устаревшим
    составом, и пересборка обязана его проигнорировать.
    """
    from apps.companies.interface import active_company_slugs

    Company.objects.filter(slug="t-beta").update(status=CompanyStatus.ARCHIVED)
    assert active_company_slugs() == ["t-alpha"]        # прогрев кэша
    Company.objects.filter(slug="t-beta").update(status=CompanyStatus.ACTIVE)
    assert active_company_slugs() == ["t-alpha"]        # кэш ещё держит старое

    holding_views.rebuild_holding_views()
    assert "co_t_beta" in _viewdef("tasks_task")


@pytest.mark.django_db(transaction=True)
def test_rebuild_is_idempotent(two_companies):
    first = holding_views.rebuild_holding_views()
    second = holding_views.rebuild_holding_views()
    assert first == second
    assert first == sorted(first)


@pytest.mark.django_db(transaction=True)
def test_view_columns_match_the_model(two_companies):
    """Ловит забытый rebuild после миграции, добавившей столбец."""
    from apps.tasks.models import Task

    holding_views.rebuild_holding_views()
    model_columns = {f.column for f in Task._meta.concrete_fields}
    view_columns = set(_view_columns("tasks_task")) - {"company_slug"}
    assert view_columns == model_columns


@pytest.mark.django_db(transaction=True)
def test_view_column_order_follows_the_model(two_companies):
    """Порядок колонок один на все ветки: он и определяет их склейку.

    Postgres сводит ветки UNION ALL по позиции, а не по имени, поэтому
    порядок обязан быть детерминированным и совпадать с моделью — иначе
    сборка ветки «по-новому» поверх старой дала бы перепутанные данные.
    """
    from apps.tasks.models import Task

    holding_views.rebuild_holding_views()
    assert _view_columns("tasks_task") == ["company_slug"] + [
        f.column for f in Task._meta.concrete_fields
    ]


@pytest.mark.django_db(transaction=True)
def test_lagging_company_schema_fails_loudly(two_companies):
    """Компания без нового столбца ломает пересборку, а не выпадает молча.

    Это цена, названная в докстринге модуля: новое поле видно холдингу
    только после того, как мигрированы ВСЕ. Важно, чтобы отставание
    проявлялось ошибкой — проглоченное исключение оставило бы сводку без
    одной компании, и цифры у директоров были бы неверными, а не
    отсутствующими.
    """
    from django.db import ProgrammingError

    with connection.cursor() as cur:
        cur.execute("ALTER TABLE co_t_beta.hr_department DROP COLUMN description")
    try:
        with pytest.raises(ProgrammingError):
            holding_views.rebuild_holding_views()
    finally:
        with connection.cursor() as cur:
            cur.execute(
                "ALTER TABLE co_t_beta.hr_department ADD COLUMN description text"
            )


@pytest.mark.django_db(transaction=True)
def test_failed_rebuild_leaves_previous_views_intact(two_companies):
    """Пересборка транзакционна: сбой на середине откатывает и снос.

    Без этого между DROP VIEW и CREATE VIEW читатель холдинга получал бы
    «relation does not exist», а падение на полпути оставляло бы часть
    представлений снесённой, часть — старой. Сбой подстраивается штатным
    для реестра способом: компания заведена, а схема ей ещё не создана.
    """
    from django.db import ProgrammingError

    before = set(holding_views.rebuild_holding_views())
    assert before

    Company.objects.create(slug="t-gamma", name="t-gamma",
                           kind=CompanyKind.SERVICE)
    with pytest.raises(ProgrammingError):
        holding_views.rebuild_holding_views()
    assert _view_names() == before


@pytest.mark.django_db(transaction=True)
def test_no_active_companies_means_no_views(db):
    """Схема holding существует, но представлений нет — а не битые вьюхи
    поверх несуществующих схем."""
    try:
        assert holding_views.rebuild_holding_views() == []
        assert _view_names() == set()
        with connection.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM information_schema.schemata "
                "WHERE schema_name = 'holding'"
            )
            assert cur.fetchone() is not None
    finally:
        _drop_holding_schema()
