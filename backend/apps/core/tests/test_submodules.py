"""Рубильники подмодулей: подмодуль гаснет вместе с родителем и сам по себе.

Реестр подмодулей — ``apps.core.models.KNOWN_SUBMODULES``. Здесь он
подменяется образцом ``probe_sub`` под существующим сервисом ``tasks``:
тесты проверяют механизм, а не список подмодулей БЗО (его проверяет
``test_bpp_scaffold.py``).
"""

import pytest
from django.core.cache import cache
from django.core.management import CommandError, call_command
from django.test import Client

from apps.companies.models import Company, CompanyKind, CompanyModule
from apps.companies.services import module_service
from apps.core.models import KNOWN_SERVICES, KNOWN_SUBMODULES, ServiceStatus
from apps.core.services import ServiceDisabled, disabled_layer, require_service, service_status
from htqweb.tenancy.db import use_company

PROBE = "probe_sub"


@pytest.fixture
def probe(monkeypatch):
    monkeypatch.setitem(KNOWN_SUBMODULES, PROBE, "tasks")
    return PROBE


@pytest.fixture
def kz(db):
    return Company.objects.create(slug="htq-kz", name="KZ", kind=CompanyKind.REGIONAL)


def _off(name: str, message: str = "Выключено") -> None:
    ServiceStatus.objects.update_or_create(
        app_label=name, defaults={"enabled": False, "message": message})
    cache.delete(f"svc-status:{name}")


def test_every_submodule_hangs_off_a_known_service():
    for sub, parent in KNOWN_SUBMODULES.items():
        assert parent in KNOWN_SERVICES, sub
        assert sub not in KNOWN_SERVICES, sub


@pytest.mark.django_db
def test_submodule_is_enabled_by_default(probe):
    assert service_status(probe) == (True, "")
    assert disabled_layer(probe) is None


@pytest.mark.django_db
def test_parent_switch_turns_the_submodule_off(probe):
    _off("tasks", "Регламент")
    assert service_status(probe) == (False, "Регламент")
    assert disabled_layer(probe) == ("tasks", "Регламент")
    with pytest.raises(ServiceDisabled) as exc:
        require_service(probe)
    # Оператор должен видеть, ЧТО включать: включать сам подмодуль бесполезно.
    assert exc.value.service == "tasks"


@pytest.mark.django_db
def test_own_switch_turns_off_only_the_submodule(probe):
    _off(probe, "Подмодуль закрыт")
    assert disabled_layer(probe) == (probe, "Подмодуль закрыт")
    assert service_status("tasks") == (True, "")


@pytest.mark.django_db
def test_company_switch_of_the_submodule(probe, kz):
    CompanyModule.objects.create(company=kz, app_label=probe, enabled=False,
                                 message="Не подключён")
    with use_company("htq-kz"):
        assert disabled_layer(probe) == (probe, "Не подключён")
    # Вне контекста компании действует только глобальный слой.
    assert service_status(probe) == (True, "")


@pytest.mark.django_db
def test_company_switch_of_the_parent_turns_the_submodule_off(probe, kz):
    CompanyModule.objects.create(company=kz, app_label="tasks", enabled=False,
                                 message="Нет задач")
    with use_company("htq-kz"):
        assert disabled_layer(probe) == ("tasks", "Нет задач")


@pytest.mark.django_db
def test_http_gate_names_the_disabled_layer(probe, monkeypatch):
    from htqweb.middleware import service_gate

    monkeypatch.setattr(service_gate, "PREFIX_TO_SERVICE",
                        {"/api/tasks/v1/probe": probe, **service_gate.PREFIX_TO_SERVICE})
    _off(probe)
    response = Client().get("/api/tasks/v1/probe/x")
    assert response.status_code == 503
    assert response.json()["service"] == probe
    # Родитель жив: его ручки доходят до авторизации вьюхи.
    assert Client().get("/api/tasks/v1/tasks/").status_code == 401

    _off("tasks")
    assert Client().get("/api/tasks/v1/probe/x").json()["service"] == "tasks"


@pytest.mark.django_db
def test_service_command_accepts_a_submodule(probe):
    call_command("service", probe, "--off")
    assert ServiceStatus.objects.get(app_label=probe).enabled is False


@pytest.mark.django_db
def test_service_command_still_rejects_unknown_names(probe):
    with pytest.raises(CommandError):
        call_command("service", "probe_sub_typo", "--off")


@pytest.mark.django_db
def test_company_modules_list_submodules_right_under_their_parent(probe, kz):
    rows = module_service.list_modules(kz)
    labels = [row["app_label"] for row in rows]
    assert labels[labels.index("tasks") + 1] == probe
    assert rows[labels.index(probe)] == {
        "app_label": probe, "enabled": True, "message": "", "is_core": False,
        "parent": "tasks",
    }
    assert all(row["parent"] is None for row in rows if row["app_label"] in KNOWN_SERVICES)


@pytest.mark.django_db
def test_company_submodule_can_be_switched(probe, kz):
    row = module_service.set_module(kz, probe, enabled=False, message="Позже")
    assert (row["parent"], row["enabled"]) == ("tasks", False)
    assert CompanyModule.objects.filter(company=kz, app_label=probe, enabled=False).exists()
