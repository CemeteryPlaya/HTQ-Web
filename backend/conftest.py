import pytest
from django.core.cache import cache


# This fixture MUST live here, at the backend root, and NOT be copied back
# into per-app tests/conftest.py files. LocMemCache (settings/test.py) is
# process-global and is NOT rolled back with the test transaction — unlike
# the DB, a ServiceStatus flip cached by services.service_status()'s 5s TTL
# survives across tests and leaks a stale "disabled" value into whichever
# test runs next, in ANY app. The repo's "duplicate per service" convention
# (see CLAUDE.md) does not apply here: that protects independently-deployed
# FastAPI microservices, whereas this is one Django process with one
# settings module and one shared in-process cache. pytest auto-discovers
# this file for every test under backend/ (pytest.ini sets no testpaths
# restriction), so one copy here covers apps/core, apps/cms, and every app
# added after them.
@pytest.fixture(autouse=True)
def clear_service_status_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture(autouse=True)
def reset_company_context(request):
    """Контекст компании не должен переживать тест.

    ``htqweb.tenancy.context._current`` — процессная ContextVar, а не
    состояние БД: транзакция теста её не откатывает. Тест, который поставил
    компанию и упал на ассерте до reset_company, оставил бы её установленной
    до конца прогона — и все последующие тесты, ожидающие пустой контекст,
    падали бы по чужой причине. Живёт рядом с clear_service_status_cache по
    той же причине: одно значение на процесс, общее для всех аппок.
    """
    from htqweb.tenancy.context import _current

    token = _current.set(None)
    yield
    _current.reset(token)

    # search_path — сессионное состояние соединения. Обычный @pytest.mark.
    # django_db откатывает его сам: Postgres SET транзакционен (см. SQL SET
    # в документации Postgres), а такой тест целиком обёрнут в atomic-блок,
    # который на teardown ВСЕГДА откатывается — это подтверждено опытом
    # (тест, выставивший co_htq_kz без ручного сброса, соседу его не оставляет).
    # Явный сброс здесь — сеть на будущее для @pytest.mark.django_db(
    # transaction=True): такие тесты не оборачиваются в atomic и не
    # откатываются, а очищаются TRUNCATE'ом, который search_path не трогает,
    # — поэтому им откат нужен сознательно, а не рассчитываться на Postgres.
    #
    # Проверяем МАРКЕР теста, а не connection.connection: pytest-django
    # блокирует БД целиком подменой BaseDatabaseWrapper.ensure_connection на
    # версию, которая безусловно бросает RuntimeError для тестов без
    # django_db — она не смотрит на то, есть ли уже открытое соединение.
    # А оно, как правило, есть: Django не закрывает соединение между тестами
    # в рамках одного процесса, поэтому "connection.connection is not None"
    # остаётся истинным для ЛЮБОГО теста, идущего после первого db-теста в
    # сессии, — включая чисто-питоновские. Проверка по факту открытого
    # соединения ловит RuntimeError на первом же не-db тесте после db-теста;
    # маркер — это именно то условие, от которого зависит сама блокировка.
    #
    # needs_rollback пропускаем отдельно: тест, намеренно поймавший
    # IntegrityError без savepoint (см. apps/companies/tests/test_models.py::
    # test_slug_is_unique), оставляет транзакцию Postgres в aborted-состоянии,
    # где ЛЮБОЙ следующий запрос, включая наш SET, запрещён до ROLLBACK —
    # который и так неизбежен на выходе из atomic-блока этого теста.
    marker = request.node.get_closest_marker("django_db")
    if marker is not None:
        from django.db import connection

        if not connection.needs_rollback:
            with connection.cursor() as cur:
                cur.execute("SET search_path TO public")


# Прод-режим подмен на один тест. Весь прогон идёт в strict (settings/test.py:
# fallback поднимает FallbackNotAllowed вместо подмены), и это правильный
# дефолт — но тесту, который проверяет ПОВЕДЕНИЕ деградации (что вьюха отдала
# 200 и пустой список, а не 500), нужен именно прод-режим. Живёт здесь, а не в
# apps/core/tests/, потому что понадобится любой аппке.
@pytest.fixture
def fallback_log_mode(settings):
    settings.FALLBACK_MODE = "log"
    return settings


# ---------------------------------------------------------------------------
# Фикстуры компаний-схем (задача 14). Общие для тестов ЛЮБОЙ будущей аппки,
# которой понадобится работать в контексте компании — поэтому живут здесь, а
# не в apps/companies/tests/, по той же логике, что и фикстуры выше.
# ---------------------------------------------------------------------------

# Слаги с префиксом "t-fixture-", а не голые "t-alpha"/"t-beta": последние
# уже заняты локальной module-scoped фикстурой
# apps/companies/tests/test_holding_views.py::company_schemas. Та фикстура
# сама сносит и пересоздаёт схему по этому слову на входе (защита от сироты
# прошлого прогона) — общий слаг означал бы, что один тестовый файл может
# снести схему, которой в этот момент владеет другой.
_SOLO_SLUG = "t-fixture-solo"
_PAIR_SLUGS = ("t-fixture-alpha", "t-fixture-beta")


def _setup_schema_pool(slugs):
    """CREATE SCHEMA + полный прогон миграций тенантных аппок по каждому слагу.

    Строка ``Company`` нужна ``migrate_company`` (пишет ``CompanySchemaVersion``
    по FK на неё), но по завершении прогона удаляется: она в public, а
    pytest-django целиком вычищает public после каждого transaction=True
    теста. Не убери её здесь — первый же тест, использующий пул, унёс бы её
    своим flush'ом, и все последующие тесты этого модуля остались бы без
    строки реестра, хотя схема физически на месте.
    """
    from apps.companies.models import Company, CompanyKind
    from apps.companies.services import migration_service, schema_service

    for slug in slugs:
        # Уборка на входе: схема, оставшаяся от прогона, упавшего до
        # teardown, не должна портить этот прогон молча.
        schema_service.drop_schema(slug)
    for slug in slugs:
        Company.objects.create(slug=slug, name=slug, kind=CompanyKind.SERVICE)
        schema_service.create_schema(slug)
        migration_service.migrate_company(slug)
    Company.objects.filter(slug__in=slugs).delete()


def _teardown_schema_pool(slugs):
    from apps.companies.models import Company
    from apps.companies.services import schema_service

    for slug in slugs:
        schema_service.drop_schema(slug)
    Company.objects.filter(slug__in=slugs).delete()


def _truncate_schema(schema: str) -> None:
    """Вычистить данные во всех таблицах схемы компании между тестами.

    Схема и миграции — часть module-scoped пула и переживают весь модуль;
    между отдельными тестами нужно убрать только строки, которые записал
    сам тест, иначе следующий тест того же модуля унаследует чужие данные.
    Список таблиц читается из information_schema, а не собирается по
    TENANT_APPS/get_models(): фикстура общая для будущих тестов всех
    тенантных аппок, и перечислять их таблицы здесь вручную значило бы
    дублировать состав миграций и молча расходиться с ним при следующей
    добавленной модели (то же предостережение, что в докстринге
    apps/companies/tests/_tenancy_test_support.py про auto-created
    M2M-таблицы, пропущенные наивным перечислением).
    """
    from django.db import connection
    from psycopg import sql

    with connection.cursor() as cur:
        cur.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = %s AND table_name != 'django_migrations'",
            [schema],
        )
        tables = [row[0] for row in cur.fetchall()]
    if not tables:
        return
    with connection.cursor() as cur:
        target = sql.SQL(", ").join(sql.Identifier(schema, t) for t in tables)
        cur.execute(sql.SQL("TRUNCATE {} CASCADE").format(target))


@pytest.fixture(scope="module")
def _solo_schema_pool(django_db_setup, django_db_blocker):
    """Одна мигрированная схема, общая на весь тестовый модуль.

    ``migrate_company`` гонит миграции четырёх тенантных аппок — около
    минуты на схему. Фикстура с областью видимости "функция" делала бы это
    на каждый тест; задача 11 (test_holding_views.py::company_schemas) уже
    столкнулась с этим и перешла на module-scoped схему с очисткой ДАННЫХ
    между тестами вместо пересоздания схемы — здесь тот же приём.

    Область не "session": держать схему живой на весь прогон репозитория
    означало бы делить её между файлами, которые пишет разный код в разное
    время и с разными ожиданиями о её содержимом и структуре (например,
    тест в этом же test_holding_views.py руками меняет структуру таблицы
    схемы через ALTER TABLE) — один файл мог бы незаметно сломать
    предпосылки другого, и порядок прогона тестов стал бы значимым. Область
    "модуль" ограничивает риск одним файлом ценой одной лишней минуты на
    каждый ФАЙЛ (не тест), который попросит эту фикстуру.

    ``django_db_blocker.unblock()`` обязателен: фикстура выполняется вне
    тела теста, где pytest-django держит доступ к БД закрытым.
    """
    with django_db_blocker.unblock():
        try:
            _setup_schema_pool((_SOLO_SLUG,))
            yield _SOLO_SLUG
        finally:
            _teardown_schema_pool((_SOLO_SLUG,))


@pytest.fixture(scope="module")
def _pair_schema_pool(django_db_setup, django_db_blocker):
    """Две мигрированные схемы, общие на весь тестовый модуль.

    См. обоснование области видимости в докстринге ``_solo_schema_pool``.
    """
    with django_db_blocker.unblock():
        try:
            _setup_schema_pool(_PAIR_SLUGS)
            yield _PAIR_SLUGS
        finally:
            _teardown_schema_pool(_PAIR_SLUGS)


@pytest.fixture
def company_schema(db, _solo_schema_pool):
    """Одна компания с полностью мигрированной схемой.

    Дорогая часть (CREATE SCHEMA + миграции) сделана один раз на модуль в
    ``_solo_schema_pool``. Здесь — только дешёвая часть на каждый тест:
    свежая строка реестра в public (типовой flush pytest-django после
    transaction=True теста уберёт её сам) и очистка данных, которые тест
    мог записать в саму схему компании (flush ограничен public и схему не
    трогает).
    """
    from apps.companies.models import Company, CompanyKind
    from htqweb.tenancy.context import schema_for

    slug = _solo_schema_pool
    company = Company.objects.create(slug=slug, name="Фикстура",
                                     kind=CompanyKind.SERVICE)
    try:
        yield {"slug": slug, "id": company.id}
    finally:
        _truncate_schema(schema_for(slug))


@pytest.fixture
def company_context(company_schema):
    """Компания из company_schema, установленная как текущая."""
    from htqweb.tenancy.db import use_company

    with use_company(company_schema["slug"]):
        yield company_schema


@pytest.fixture
def two_company_schemas(db, _pair_schema_pool):
    """Две мигрированные схемы — для проверок изоляции между компаниями.

    Реестр заводится заново на каждый тест поверх готового module-scoped
    пула схем (см. ``_pair_schema_pool``); данные, записанные тестом в обе
    схемы, чистятся на выходе так же, как в ``company_schema``.
    """
    from apps.companies.models import Company, CompanyKind
    from htqweb.tenancy.context import schema_for

    slugs = _pair_schema_pool
    for slug in slugs:
        Company.objects.create(slug=slug, name=slug, kind=CompanyKind.SERVICE)
    try:
        yield slugs
    finally:
        for slug in slugs:
            _truncate_schema(schema_for(slug))
