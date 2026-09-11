"""Задача 1 плана A: аппка заведена, смонтирована и стоит в реестре модулей.

Тесты БД не касаются намеренно (ни одного ``django_db``): проверяется состав
установки, а не данные.
"""

import importlib

import pytest
from django.conf import settings
from django.urls import resolve


def test_access_is_not_a_tenant_app():
    """Роль одна на все компании (спека §1.3), значит таблицы в public."""
    assert "access" not in settings.TENANT_APPS


def test_access_has_no_holding_module():
    """``holding.py`` обязателен только тенантным аппкам.

    У общей аппки его быть не должно: пустой ``HOLDING_MODELS`` означал бы,
    что её кто-то собирался сводить в схему холдинга.
    """
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("apps.access.holding")


def test_prefix_is_mounted():
    assert resolve("/api/access/v1/roles").func is not None


def test_both_spellings_of_the_path_resolve():
    """``APPEND_SLASH = False``: оба написания регистрируются явно.

    Сравниваются КЛАССЫ вьюх, а не функции: каждый вызов ``as_view()``
    возвращает новую обёртку, поэтому равенство функций не выполняется даже
    для одного и того же класса.
    """
    bare = resolve("/api/access/v1/roles").func
    slashed = resolve("/api/access/v1/roles/").func
    assert bare.view_class is slashed.view_class


def test_access_is_a_known_service():
    from apps.core.models import KNOWN_SERVICES

    assert "access" in KNOWN_SERVICES


def test_access_is_a_core_module():
    """Выключенный доступ означал бы «ни у кого нет прав» — это не режим работы."""
    from apps.core.services import CORE_MODULES

    assert "access" in CORE_MODULES


def test_gate_knows_the_prefix():
    from htqweb.middleware.service_gate import PREFIX_TO_SERVICE

    assert PREFIX_TO_SERVICE["/api/access/"] == "access"
