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
