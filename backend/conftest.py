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


# Прод-режим подмен на один тест. Весь прогон идёт в strict (settings/test.py:
# fallback поднимает FallbackNotAllowed вместо подмены), и это правильный
# дефолт — но тесту, который проверяет ПОВЕДЕНИЕ деградации (что вьюха отдала
# 200 и пустой список, а не 500), нужен именно прод-режим. Живёт здесь, а не в
# apps/core/tests/, потому что понадобится любой аппке.
@pytest.fixture
def fallback_log_mode(settings):
    settings.FALLBACK_MODE = "log"
    return settings
