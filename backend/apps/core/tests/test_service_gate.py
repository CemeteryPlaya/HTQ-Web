import pytest
from django.core.cache import cache
from django.test import Client

from apps.core.models import ServiceStatus
from apps.core.services import ServiceDisabled, require_service, service_enabled


@pytest.fixture(autouse=True)
def clear_service_status_cache():
    # LocMemCache (settings/test.py) persists across tests in the same
    # process; the 5s TTL in services._status() can otherwise leak a
    # cached value from a previous test's DB state into this one.
    cache.clear()
    yield
    cache.clear()


@pytest.mark.django_db
def test_unknown_service_enabled_by_default():
    assert service_enabled("cms") is True


@pytest.mark.django_db
def test_disabled_service_blocks_http():
    ServiceStatus.objects.update_or_create(app_label="cms", defaults={"enabled": False})
    resp = Client().get("/api/cms/v1/news/")
    assert resp.status_code == 503
    body = resp.json()
    assert body["code"] == "service_disabled"
    assert body["service"] == "cms"
    assert "detail" in body


@pytest.mark.django_db
def test_disabled_service_blocks_internal_calls():
    ServiceStatus.objects.update_or_create(app_label="hr", defaults={"enabled": False})
    with pytest.raises(ServiceDisabled):
        require_service("hr")


@pytest.mark.django_db
def test_other_services_unaffected():
    ServiceStatus.objects.update_or_create(app_label="cms", defaults={"enabled": False})
    assert Client().get("/health/").status_code == 200


@pytest.mark.django_db
def test_status_endpoint_lists_conference_disabled():
    resp = Client().get("/api/core/v1/services/")
    assert resp.status_code == 200
    assert resp.json()["services"]["conference"] is False  # сид из миграции
