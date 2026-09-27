"""Модуль БЗО, этап 0: четыре новые аппки установлены, смонтированы и
отключаемы; подмодули bpp гейтятся раньше модуля и называют выключенный слой.

Мастер-план: docs/plans/2026-09-26-bpp-master-plan.md, §2.1 и §2.3.
"""

from __future__ import annotations

import pytest
from django.apps import apps as django_apps
from django.core.cache import cache
from django.test import Client
from django.urls import get_resolver
from django.urls.resolvers import URLResolver

from apps.access import registry
from apps.core.models import KNOWN_SERVICES, KNOWN_SUBMODULES, ServiceStatus
from apps.core.services import CORE_MODULES
from htqweb.middleware.service_gate import PREFIX_TO_SERVICE

SCAFFOLD = [
    ("project", "api/project/v1/"),
    ("refdata", "api/refdata/v1/"),
    ("notifications", "api/notifications/v1/"),
    ("bpp", "api/bpp/v1/"),
]

SUBMODULE_PATHS = [
    ("bpp_budget", "/api/bpp/v1/budgets/x"),
    ("bpp_requests", "/api/bpp/v1/requests/x"),
    ("bpp_requests", "/api/bpp/v1/plan/x"),
    ("bpp_agreements", "/api/bpp/v1/agreements/x"),
    ("bpp_invoices", "/api/bpp/v1/invoices/x"),
    ("bpp_bank", "/api/bpp/v1/bank/x"),
    ("bpp_alternatives", "/api/bpp/v1/alternatives/x"),
    ("bpp_alternatives", "/api/bpp/v1/kpi/x"),
    ("bpp_accountable", "/api/bpp/v1/accountable/x"),
]


def _off(name: str) -> None:
    ServiceStatus.objects.update_or_create(app_label=name, defaults={"enabled": False})
    cache.delete(f"svc-status:{name}")


@pytest.mark.parametrize("label,prefix", SCAFFOLD)
def test_app_is_installed_registered_and_mounted(label, prefix):
    config = django_apps.get_app_config(label)
    assert config.name == f"apps.{label}"
    assert config.API_PREFIX == prefix
    assert label in KNOWN_SERVICES
    mounted = {str(entry.pattern) for entry in get_resolver().url_patterns
               if isinstance(entry, URLResolver)}
    assert prefix in mounted


@pytest.mark.django_db
@pytest.mark.parametrize("label,prefix", SCAFFOLD)
def test_app_404s_when_enabled_and_503s_when_disabled(label, prefix):
    assert Client().get(f"/{prefix}__probe__").status_code == 404
    _off(label)
    body = Client().get(f"/{prefix}__probe__").json()
    assert (body["code"], body["service"]) == ("service_disabled", label)


def test_platform_parts_are_core_and_bpp_is_switchable_per_company():
    assert {"project", "refdata", "notifications"} <= CORE_MODULES
    assert "bpp" not in CORE_MODULES


def test_every_bpp_submodule_is_declared_and_gated():
    assert set(KNOWN_SUBMODULES) == {sub for sub, _path in SUBMODULE_PATHS}
    assert set(KNOWN_SUBMODULES.values()) == {"bpp"}
    assert set(KNOWN_SUBMODULES) <= set(PREFIX_TO_SERVICE.values())


def test_submodule_prefixes_precede_their_module_prefix():
    """Гейт берёт ПЕРВОЕ совпадение: префикс модуля выше префикса подмодуля
    молча отключил бы рубильник подмодуля."""
    order = list(PREFIX_TO_SERVICE)
    for prefix, name in PREFIX_TO_SERVICE.items():
        parent = KNOWN_SUBMODULES.get(name)
        if parent is None:
            continue
        covering = [p for p, n in PREFIX_TO_SERVICE.items()
                    if n == parent and prefix.startswith(p)]
        assert covering, f"{prefix}: нет префикса родителя {parent}"
        assert all(order.index(prefix) < order.index(p) for p in covering), prefix


@pytest.mark.django_db
@pytest.mark.parametrize("sub,path", SUBMODULE_PATHS)
def test_submodule_switch_closes_only_its_paths(sub, path):
    _off(sub)
    response = Client().get(path)
    assert response.status_code == 503
    assert response.json()["service"] == sub
    assert Client().get("/api/bpp/v1/dashboard/x").status_code == 404


@pytest.mark.django_db
@pytest.mark.parametrize("sub,neighbour", [
    ("bpp_bank", "/api/bpp/v1/bank-accounts/x"),
    ("bpp_requests", "/api/bpp/v1/planning/x"),
])
def test_submodule_prefix_stops_at_a_path_segment(sub, neighbour):
    """Префикс подмодуля без завершающего «/» (голый путь коллекции тоже
    должен гейтиться) не имеет права захватывать соседний путь с тем же
    началом: счета организации — не выписки, и гасить их рубильником
    ``bpp_bank`` нельзя."""
    _off(sub)
    assert Client().get(neighbour).status_code == 404
    assert Client().get(neighbour.rsplit("/", 2)[0] + "/" + {
        "bpp_bank": "bank", "bpp_requests": "plan"}[sub]).status_code == 503


@pytest.mark.django_db
def test_bpp_switch_closes_every_submodule_and_names_itself():
    _off("bpp")
    for _sub, path in SUBMODULE_PATHS:
        assert Client().get(path).json()["service"] == "bpp", path


def test_bpp_nodes_are_in_the_access_registry():
    paths = registry.paths()
    for node in ("bpp", "bpp.budgets", "bpp.invoices.decision", "bpp.articles.supply",
                 "bpp.articles.pm", "project.projects", "refdata.articles", "notifications"):
        assert node in paths, node
    # Подмодуль — выключатель, а не модуль прав.
    assert not set(KNOWN_SUBMODULES) & paths
