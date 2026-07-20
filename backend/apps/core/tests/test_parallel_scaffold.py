"""prep 4.0 (PLAN.md §5) — скаффолд 5 доменных аппок + URL-автодискавери.

Фундамент параллельной разработки (Поток A / Поток B). Проверяет, что каждая
доменная аппка:
  * установлена и объявляет ``AppConfig.API_PREFIX``;
  * автоматически смонтирована в корневой URLconf через автодискавери
    (без ручной строки ``include(...)`` в ``htqweb/urls.py``);
  * отключаема — путь под её префиксом отдаёт 503-конверт при выключенном
    сервисе и 404 (не 500) при включённом, пока роутов нет;
  * имеет ``interface.py``-заглушку с ``require_service(...)`` первой строкой.
"""
from __future__ import annotations

import importlib

import pytest
from django.apps import apps as django_apps
from django.core.cache import cache
from django.test import Client
from django.urls import get_resolver
from django.urls.resolvers import URLResolver

from apps.core.models import ServiceStatus
from apps.core.services import ServiceDisabled

# (app_label, API_PREFIX, service_name). Префикс approvals/mail — по URL
# (requests/email), а не по имени сервиса (см. PREFIX_TO_SERVICE).
SCAFFOLD = [
    ("hr", "api/hr/v1/", "hr"),
    ("tasks", "api/tasks/v1/", "tasks"),
    ("approvals", "api/requests/v1/", "approvals"),
    ("mail", "api/email/v1/", "mail"),
    ("messenger", "api/messenger/v1/", "messenger"),
]


def _root_mounted_prefixes() -> set[str]:
    return {
        str(entry.pattern)
        for entry in get_resolver().url_patterns
        if isinstance(entry, URLResolver)
    }


@pytest.mark.parametrize("label,prefix,service", SCAFFOLD)
def test_scaffold_app_installed_with_api_prefix(label, prefix, service):
    config = django_apps.get_app_config(label)  # LookupError, пока аппки нет
    assert config.name == f"apps.{label}"
    assert getattr(config, "API_PREFIX", None) == prefix


@pytest.mark.parametrize("label,prefix,service", SCAFFOLD)
def test_autodiscovery_mounts_scaffold_app(label, prefix, service):
    assert prefix in _root_mounted_prefixes()


def test_autodiscovery_still_mounts_existing_domains():
    mounted = _root_mounted_prefixes()
    for prefix in ("api/cms/v1/", "api/users/v1/", "api/media/v1/"):
        assert prefix in mounted


@pytest.mark.django_db
@pytest.mark.parametrize("label,prefix,service", SCAFFOLD)
def test_scaffold_app_503s_when_service_disabled(label, prefix, service):
    ServiceStatus.objects.update_or_create(app_label=service, defaults={"enabled": False})
    cache.delete(f"svc-status:{service}")
    resp = Client().get(f"/{prefix}__gate_probe__")
    assert resp.status_code == 503
    body = resp.json()
    assert set(body) == {"detail", "code", "service"}
    assert body["code"] == "service_disabled"
    assert body["service"] == service


@pytest.mark.django_db
@pytest.mark.parametrize("label,prefix,service", SCAFFOLD)
def test_scaffold_app_404s_when_enabled_no_routes(label, prefix, service):
    # Сервис включён (строки в реестре нет → default enabled), роутов ещё
    # нет → путь под префиксом даёт 404, а не 500 (пустой urls смонтирован).
    resp = Client().get(f"/{prefix}__no_such_route__")
    assert resp.status_code == 404


# ── interface.py заглушки (§7): импортируемы, guard первой строкой ──────────
_INTERFACE = [
    ("hr", "get_department_brief", (1,), "hr"),
    ("messenger", "dispatch_notification", ([1], {"x": 1}), "messenger"),
    ("mail", "archive_user_mailboxes", (1,), "mail"),
    ("tasks", "get_task_brief", (1,), "tasks"),
]


@pytest.mark.parametrize("label,func,args,service", _INTERFACE)
def test_interface_stub_importable(label, func, args, service):
    mod = importlib.import_module(f"apps.{label}.interface")
    assert callable(getattr(mod, func))


@pytest.mark.django_db
@pytest.mark.parametrize("label,func,args,service", _INTERFACE)
def test_interface_stub_guards_service_first(label, func, args, service):
    # Первая строка каждой заглушки — require_service(service): при выключенном
    # сервисе вызов падает ServiceDisabled ДО NotImplementedError (что и
    # доказывает, что guard стоит первым).
    ServiceStatus.objects.update_or_create(app_label=service, defaults={"enabled": False})
    cache.delete(f"svc-status:{service}")
    mod = importlib.import_module(f"apps.{label}.interface")
    with pytest.raises(ServiceDisabled):
        getattr(mod, func)(*args)


def test_approvals_interface_module_importable():
    # approvals межаппных функций не производит (§7), но модуль-заглушка есть.
    importlib.import_module("apps.approvals.interface")
