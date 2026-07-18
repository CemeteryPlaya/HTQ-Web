import pytest
from django.core.cache import cache


@pytest.fixture(autouse=True)
def clear_service_status_cache():
    # LocMemCache (settings/test.py) persists across tests in the same
    # process; the 5s TTL in services.service_status() can otherwise leak a
    # cached value from a previous test's DB state into this one.
    cache.clear()
    yield
    cache.clear()
