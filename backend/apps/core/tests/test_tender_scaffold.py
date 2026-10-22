"""Тендерный модуль, этап 0 (T0.1): аппка tender установлена, смонтирована
и отключаема — глобально и у одной компании; под гейтом прав с рождения.

Мастер-план: docs/plans/2026-10-06-tender-master-plan.md, §3.1 и §4 (T0.1).
"""

from __future__ import annotations

import pytest
from django.apps import apps as django_apps
from django.core.cache import cache
from django.test import Client
from django.urls import get_resolver
from django.urls.resolvers import URLResolver

from apps.access import depth, registry
from apps.access.models import RolePermission
from apps.access.self_service import SELF_SERVICE, TRANSLATED_APPS
from apps.companies.models import Company, CompanyKind, CompanyModule
from apps.core.models import KNOWN_SERVICES, ServiceStatus
from apps.core.services import CORE_MODULES
from htqweb.middleware.service_gate import PREFIX_TO_SERVICE

PREFIX = "api/tender/v1/"
PROBE = f"/{PREFIX}__probe__"


def _off(name: str) -> None:
    ServiceStatus.objects.update_or_create(app_label=name, defaults={"enabled": False})
    cache.delete(f"svc-status:{name}")


def test_app_is_installed_registered_and_mounted():
    config = django_apps.get_app_config("tender")
    assert config.name == "apps.tender"
    assert config.API_PREFIX == PREFIX
    assert "tender" in KNOWN_SERVICES
    mounted = {str(entry.pattern) for entry in get_resolver().url_patterns
               if isinstance(entry, URLResolver)}
    assert PREFIX in mounted


def test_tender_is_switchable_per_company_not_core():
    """Рубильник по компании (T-01): пилот включается только у холдинга."""
    assert "tender" not in CORE_MODULES
    assert PREFIX_TO_SERVICE.get("/api/tender/") == "tender"


@pytest.mark.django_db
def test_app_404s_when_enabled_and_503s_when_disabled():
    assert Client().get(PROBE).status_code == 404
    _off("tender")
    response = Client().get(PROBE)
    assert response.status_code == 503
    body = response.json()
    assert (body["code"], body["service"]) == ("service_disabled", "tender")


@pytest.mark.django_db
def test_company_switch_closes_only_that_company():
    kz = Company.objects.create(slug="htq-kz", name="KZ", kind=CompanyKind.REGIONAL)
    Company.objects.create(slug="htq-uz", name="UZ", kind=CompanyKind.REGIONAL)
    CompanyModule.objects.create(company=kz, app_label="tender", enabled=False,
                                 message="Не подключён")

    closed = Client().get(PROBE, HTTP_X_HTQ_COMPANY="htq-kz")
    assert closed.status_code == 503
    assert closed.json()["service"] == "tender"
    assert Client().get(PROBE, HTTP_X_HTQ_COMPANY="htq-uz").status_code == 404


def test_tender_is_born_under_the_gate():
    """Как аппки БЗО: каждая ручка — под api_view(module=…, level=…);
    исключения самообслуживания (портал поставщика) появятся с этапом 3."""
    assert "tender" in TRANSLATED_APPS
    assert SELF_SERVICE["tender"] == {}


def test_tender_is_a_rights_module():
    assert "tender" in registry.paths()


@pytest.mark.django_db
def test_platform_admin_has_full_access_to_tender():
    row = RolePermission.objects.get(role__code="platform-admin", node="tender")
    assert row.flags == frozenset(depth.FLAGS)
