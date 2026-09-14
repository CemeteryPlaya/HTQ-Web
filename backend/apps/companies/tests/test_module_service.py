"""Рубильник модулей одной компании (второй слой над ServiceStatus)."""

import pytest
from django.core.cache import cache

from apps.companies import interface
from apps.companies.models import Company, CompanyKind, CompanyModule
from apps.companies.services import module_service
from apps.core.models import KNOWN_SERVICES
from apps.core.services import CORE_MODULES


@pytest.fixture
def company(db):
    return Company.objects.create(slug="htq", name="HTQ", kind=CompanyKind.CONSTRUCTION)


@pytest.mark.django_db
def test_list_covers_every_known_service_and_defaults_to_enabled(company):
    rows = module_service.list_modules(company)
    assert [r["app_label"] for r in rows] == list(KNOWN_SERVICES)
    assert all(r["enabled"] for r in rows)
    assert {r["app_label"] for r in rows if r["is_core"]} == set(CORE_MODULES) & set(KNOWN_SERVICES)


@pytest.mark.django_db
def test_disable_writes_row_and_interface_sees_it(company):
    row = module_service.set_module(company, "tasks", enabled=False, message="Пока закрыто")
    assert row == {"app_label": "tasks", "enabled": False, "message": "Пока закрыто", "is_core": False}
    cache.clear()  # interface кэширует ответ на 5 секунд
    assert interface.module_enabled("htq", "tasks") == (False, "Пока закрыто")


@pytest.mark.django_db
def test_enable_removes_the_row_because_absence_means_enabled(company):
    module_service.set_module(company, "tasks", enabled=False)
    module_service.set_module(company, "tasks", enabled=True)
    assert not CompanyModule.objects.filter(company=company, app_label="tasks").exists()
    cache.clear()
    assert interface.module_enabled("htq", "tasks")[0] is True


@pytest.mark.django_db
def test_core_module_cannot_be_disabled(company):
    with pytest.raises(module_service.CoreModuleLocked):
        module_service.set_module(company, "hr", enabled=False)
    assert not CompanyModule.objects.filter(company=company).exists()


@pytest.mark.django_db
def test_unknown_module_is_rejected(company):
    with pytest.raises(module_service.UnknownModule):
        module_service.set_module(company, "warehouse", enabled=False)
