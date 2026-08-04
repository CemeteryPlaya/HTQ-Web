import pytest
from django.core.cache import cache
from django.test import Client

from apps.core.models import ServiceStatus
from apps.core.services import ServiceDisabled, require_service, service_enabled, service_status


@pytest.mark.django_db
def test_unknown_service_enabled_by_default():
    assert service_enabled("not-a-real-service") is True
    # require_service must be a no-op (not raise) for names absent from the registry
    require_service("not-a-real-service")


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
def test_status_endpoint_lists_conference_enabled():
    """Раньше здесь ждали False: SFU-стек был отложен и сидировался
    выключенным (миграция ``core/0001``). Стек поднят — ``core/0003``
    включает сервис, и реестр должен это показывать."""
    resp = Client().get("/api/core/v1/services/")
    assert resp.status_code == 200
    assert resp.json()["services"]["conference"] is True


@pytest.mark.django_db
def test_cache_outage_falls_back_to_db_fail_open(monkeypatch):
    """Finding 5: an unreachable Redis must not mean 'everything is disabled'.
    A cache.get failure must fall back to querying the DB directly."""
    ServiceStatus.objects.update_or_create(app_label="cms", defaults={"enabled": True})

    def boom_get(*a, **kw):
        raise ConnectionError("redis unreachable")

    def boom_set(*a, **kw):
        raise ConnectionError("redis unreachable")

    monkeypatch.setattr(cache, "get", boom_get)
    monkeypatch.setattr(cache, "set", boom_set)

    enabled, _message = service_status("cms")
    assert enabled is True


@pytest.mark.django_db
def test_db_failure_during_status_lookup_still_raises(monkeypatch):
    """The DB is the source of truth: a DB failure must NOT be silently
    swallowed the way a cache failure is."""
    from apps.core.models import ServiceStatus as SS

    def boom_filter(*a, **kw):
        raise RuntimeError("db unreachable")

    monkeypatch.setattr(SS.objects, "filter", boom_filter)

    with pytest.raises(RuntimeError):
        service_status("cms")
