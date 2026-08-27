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

import io

import pytest
from django.conf import settings as django_settings
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import DatabaseError, ProgrammingError, connection

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


def _name_column_type(slug: str) -> str:
    with connection.cursor() as cur:
        cur.execute(
            "SELECT character_maximum_length FROM information_schema.columns "
            "WHERE table_schema = %s AND table_name = 'hr_department' "
            "AND column_name = 'name'",
            [f"co_{slug.replace('-', '_')}"],
        )
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

    ``include_public=False`` не косметика: с public в пути имя
    ``hr_department`` разрешилось бы в ОБЩУЮ таблицу тестовой БД, если бы в
    схеме компании её вдруг не оказалось, и ``CASCADE`` вычистил бы её.
    Сегодня недостижимо, стоит ноль.
    """
    from htqweb.tenancy.db import use_company

    for slug in SLUGS:
        with use_company(slug, include_public=False):
            with connection.cursor() as cur:
                cur.execute("TRUNCATE hr_department CASCADE")


# --------------------------------------------------------------------------
# Автообнаружение сводимых моделей
# --------------------------------------------------------------------------

def test_holding_models_covers_every_tenant_app():
    """КАЖДАЯ тенантная аппка объявляет состав, и имена резолвятся в модели.

    Сверка идёт с settings.TENANT_APPS, а не с захардкоженным списком:
    пятая тенантная аппка, заведённая без holding.py, обязана уронить этот
    тест, а не пройти мимо него.
    """
    labels = {model._meta.app_label for model in holding_views.holding_models()}
    assert labels == set(django_settings.TENANT_APPS)


def test_tenant_app_without_holding_module_is_an_error(settings):
    """Тенантная аппка без holding.py — ошибка, а не «нечего сводить».

    Молчаливый пропуск убрал бы из сводок целую аппку: цифры у директоров
    стали бы НЕВЕРНЫМИ, а не отсутствующими. Аппке, которой сводить нечего,
    положено написать HOLDING_MODELS = () явно.
    """
    settings.TENANT_APPS = (*settings.TENANT_APPS, "cms")
    with pytest.raises(ImproperlyConfigured, match="cms"):
        holding_views.holding_models()


def test_holding_module_without_declaration_is_an_error(monkeypatch):
    """holding.py без HOLDING_MODELS — опечатка, и стоит того же."""
    import apps.signoff.holding as module

    monkeypatch.delattr(module, "HOLDING_MODELS")
    with pytest.raises(ImproperlyConfigured, match="HOLDING_MODELS"):
        holding_views.holding_models()


# --------------------------------------------------------------------------
# Сборка представлений
# --------------------------------------------------------------------------

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
    # Без проверки на дубликаты коллизия db_table между двумя объявленными
    # моделями была бы невидима: вторая затёрла бы первую через DROP+CREATE,
    # а множества всё равно совпали бы.
    assert len(created) == len(set(created))
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
def test_rebuild_takes_the_lock_before_reading_the_company_list(two_companies,
                                                               monkeypatch):
    """Список компаний читается ПОД взаимным исключением, а не до него.

    Иначе две параллельные пересборки читают состав независимо: A увидела
    [x], B увидела [x, y], B закоммитилась первой, A легла поверх — компания
    y пропала из сводок без ошибки и без следа. fresh=True закрывает кэш, но
    не эту гонку.

    Проверяется из ВТОРОГО соединения: pg_try_advisory_lock оттуда обязан
    вернуть false в тот момент, когда пересборка читает список.
    """
    import psycopg

    from apps.companies.interface import active_company_slugs
    from apps.companies.services.migration_service import ADVISORY_LOCK_KEY

    seen: dict[str, bool] = {}
    db = connection.settings_dict

    def probe(*, fresh: bool = False):
        with psycopg.connect(host=db["HOST"], port=db["PORT"], dbname=db["NAME"],
                             user=db["USER"], password=db["PASSWORD"],
                             autocommit=True) as other:
            with other.cursor() as cur:
                cur.execute("SELECT pg_try_advisory_lock(%s)", [ADVISORY_LOCK_KEY])
                got = cur.fetchone()[0]
                seen["free"] = got
                if got:
                    cur.execute("SELECT pg_advisory_unlock(%s)", [ADVISORY_LOCK_KEY])
        return active_company_slugs(fresh=fresh)

    monkeypatch.setattr(holding_views, "active_company_slugs", probe)
    holding_views.rebuild_holding_views()
    assert seen["free"] is False


@pytest.mark.django_db(transaction=True)
def test_rebuild_is_idempotent(two_companies):
    first = holding_views.rebuild_holding_views()
    before = _viewdef("tasks_task")
    second = holding_views.rebuild_holding_views()
    assert first == second
    assert first == sorted(first)
    # Совпадения имён мало: пересборка, давшая те же имена, но другой состав
    # веток, прошла бы такую проверку.
    assert _viewdef("tasks_task") == before


@pytest.mark.django_db(transaction=True)
def test_rebuild_removes_orphan_views(two_companies):
    """Представление модели, убранной из HOLDING_MODELS, не остаётся жить.

    Сирота продолжала бы блокировать contract-миграции по своей таблице,
    причём пересборка о ней бы уже не знала — то есть блокировка была бы
    вечной и без видимой причины.
    """
    holding_views.rebuild_holding_views()
    with connection.cursor() as cur:
        cur.execute(
            "CREATE VIEW holding.zz_orphan AS "
            "SELECT id FROM co_t_alpha.hr_department"
        )
    assert "zz_orphan" in _view_names()

    holding_views.rebuild_holding_views()
    assert "zz_orphan" not in _view_names()


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


# --------------------------------------------------------------------------
# Снос: представления блокируют contract-миграции
# --------------------------------------------------------------------------

@pytest.mark.django_db(transaction=True)
def test_views_block_contract_migrations(two_companies):
    """Главная цена решения, закреплённая тестом.

    Пока представление существует, Postgres запрещает удалить столбец его
    таблицы и сменить его тип — то есть RemoveField и AlterField по любой
    сводимой модели. Ради этого и заведена пара drop/rebuild; если Postgres
    когда-нибудь перестанет так делать, тест обязан покраснеть, а не тихо
    оставить в коде лишнюю машинерию.
    """
    holding_views.rebuild_holding_views()

    with connection.cursor() as cur:
        with pytest.raises(DatabaseError, match="depend"):
            cur.execute("ALTER TABLE co_t_alpha.hr_department "
                        "DROP COLUMN description")
    with connection.cursor() as cur:
        with pytest.raises(DatabaseError, match="used by a view"):
            cur.execute("ALTER TABLE co_t_alpha.hr_department "
                        "ALTER COLUMN name TYPE varchar(300)")


@pytest.mark.django_db(transaction=True)
def test_drop_holding_views_unblocks_contract_migrations(two_companies):
    """Пара «снести до, собрать после» действительно расшивает contract."""
    built = set(holding_views.rebuild_holding_views())
    assert "hr_department" in built

    dropped = holding_views.drop_holding_views()
    assert set(dropped) == built
    assert _view_names() == set()

    try:
        with connection.cursor() as cur:
            cur.execute("ALTER TABLE co_t_alpha.hr_department "
                        "ALTER COLUMN name TYPE varchar(300)")
        assert _name_column_type("t-alpha") == 300
        assert set(holding_views.rebuild_holding_views()) == built
    finally:
        holding_views.drop_holding_views()
        with connection.cursor() as cur:
            cur.execute("ALTER TABLE co_t_alpha.hr_department "
                        "ALTER COLUMN name TYPE varchar(255)")


@pytest.mark.django_db(transaction=True)
def test_drop_holding_views_is_idempotent(two_companies):
    holding_views.rebuild_holding_views()
    assert holding_views.drop_holding_views()
    assert holding_views.drop_holding_views() == []
    assert _view_names() == set()


# --------------------------------------------------------------------------
# Команда migrate_companies
# --------------------------------------------------------------------------

@pytest.mark.django_db(transaction=True)
def test_command_drops_views_before_migrating_and_rebuilds_after(two_companies,
                                                                 monkeypatch):
    """Единственный тест, который ловит регресс порядка в команде.

    Настоящей contract-миграции в наборе нет, поэтому прогон подменяется
    функцией, выполняющей ровно тот SQL, который порождает AlterField со
    сменой типа. Утверждение при этом поведенческое, а не «вызвался ли
    метод»: без предварительного сноса Postgres этот ALTER просто запретит.
    """
    holding_views.rebuild_holding_views()
    built = _view_names()
    assert built

    def fake_migrate(slug, *, app_label=None, target=None, plan=False):
        schema = "co_" + slug.replace("-", "_")
        with connection.cursor() as cur:
            cur.execute(f"ALTER TABLE {schema}.hr_department "
                        f"ALTER COLUMN name TYPE varchar(300)")
        return {"applied": {}, "planned": []}

    monkeypatch.setattr(migration_service, "migrate_company", fake_migrate)
    try:
        call_command("migrate_companies", stdout=io.StringIO())
        for slug in SLUGS:
            assert _name_column_type(slug) == 300
        assert _view_names() == built
    finally:
        holding_views.drop_holding_views()
        with connection.cursor() as cur:
            for slug in SLUGS:
                schema = "co_" + slug.replace("-", "_")
                cur.execute(f"ALTER TABLE {schema}.hr_department "
                            f"ALTER COLUMN name TYPE varchar(255)")


@pytest.mark.django_db(transaction=True)
def test_command_plan_leaves_views_untouched(two_companies):
    """Сухой прогон ничего не меняет — ронять ради него сводки нельзя."""
    holding_views.rebuild_holding_views()
    before = (_view_names(), _viewdef("tasks_task"))

    call_command("migrate_companies", "--plan", stdout=io.StringIO())

    assert (_view_names(), _viewdef("tasks_task")) == before


@pytest.mark.django_db(transaction=True)
def test_command_leaves_views_dropped_when_rebuild_fails(two_companies):
    """Частичный прогон: миграции прошли, сводку собрать нельзя.

    Вьюхи остаются снесёнными намеренно — снесённая даёт читателю громкую
    ошибку, то есть верно отражает состояние группы, а собранная по старому
    составу молча врёт. Код возврата ненулевой: работа не доведена.
    """
    holding_views.rebuild_holding_views()
    assert _view_names()

    # Компания заведена, схема ей ещё не создана — финальная пересборка на
    # ней и споткнётся, хотя миграции обработанных компаний прошли.
    Company.objects.create(slug="t-gamma", name="t-gamma",
                           kind=CompanyKind.SERVICE)
    with pytest.raises(CommandError, match="сводки холдинга собрать нельзя"):
        call_command("migrate_companies", "--company", "t-alpha",
                     stdout=io.StringIO())

    assert _view_names() == set()


@pytest.mark.django_db(transaction=True)
def test_command_checks_slug_before_dropping_views(two_companies):
    """Опечатка в --company не имеет права ронять сводки холдинга.

    Проверка реестра идёт ДО сноса: иначе неверный аргумент оставлял бы
    холдинг без цифр до следующего успешного прогона.
    """
    holding_views.rebuild_holding_views()
    before = _view_names()
    assert before

    with pytest.raises(CommandError, match="Нет в реестре"):
        call_command("migrate_companies", "--company", "t-nope",
                     stdout=io.StringIO())

    assert _view_names() == before
