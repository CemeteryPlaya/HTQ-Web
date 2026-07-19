import pytest
from django.core.cache import cache


@pytest.fixture(autouse=True)
def clear_service_status_cache():
    # Same rationale as apps/core/tests/conftest.py: LocMemCache persists
    # across tests in-process (DB transaction rollback does NOT roll back the
    # cache), so a ServiceStatus flip in one test can leak into the next via
    # the 5s TTL in services.service_status() unless we clear it here too.
    cache.clear()
    yield
    cache.clear()
