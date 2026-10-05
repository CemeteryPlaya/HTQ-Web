"""Подмодули ``bpp`` подключаются сами (план этапа 2 A, задача 2) —
``models/__init__.py`` и ``urls.py`` больше не держат явную строку на
каждый подмодуль: файл с ``__all__``/``urlpatterns`` в пакете достаточен
сам по себе. Тест проверяет устройство автодискавери — что оно ничего не
забывает и не путает порядок, — а не список сегодняшних подмодулей: он
вырастет без правки этого файла.
"""

from __future__ import annotations

import importlib
import pkgutil
import sys
import types

import pytest
from django.urls import path, resolve
from django.urls.resolvers import RegexPattern, URLResolver

from apps.bpp import models, urls as bpp_urls


def test_every_models_submodule_is_imported_into_the_package():
    """Каждый неприватный модуль пакета ``models`` подключён, и пакет несёт
    в своём пространстве имён все имена его ``__all__``."""
    seen = False
    for _, name, is_pkg in pkgutil.iter_modules(models.__path__):
        if is_pkg or name.startswith("_"):
            continue
        module = importlib.import_module(f"apps.bpp.models.{name}")
        for symbol in getattr(module, "__all__", ()):
            seen = True
            assert getattr(models, symbol, None) is getattr(module, symbol), (name, symbol)
    assert seen, "в пакете models не нашлось ни одного __all__ — тест ничего не проверил"


def test_models_core_is_imported_first_then_alphabetical():
    """``core`` — раньше остальных: от него зависят их модели (``BppModel``,
    ``VersionedModel``). Дальше — по алфавиту, порядок не должен зависеть от
    того, в каком порядке лежат файлы на диске."""
    names = models._submodule_names()
    assert names[0] == "core"
    assert names[1:] == sorted(names[1:])
    assert len(names) == len(set(names))


def test_fake_urls_submodule_is_wired_and_resolvable(monkeypatch):
    """Подставной ``urls_probe.py`` — как реальный подмодуль: любой файл
    ``urls_*.py`` пакета подключается без правки ``urls.py``."""

    def probe_view(request):
        return None

    probe = types.ModuleType("apps.bpp.urls_probe")
    probe.urlpatterns = [path("probe-only/", probe_view, name="bpp-probe")]
    sys.modules["apps.bpp.urls_probe"] = probe
    monkeypatch.setattr(bpp_urls, "_submodule_names", lambda: ["urls_probe"])
    try:
        patterns = bpp_urls._submodule_patterns()
        assert len(patterns) == 1
        resolver = URLResolver(RegexPattern(r"^"), patterns)
        match = resolver.resolve("probe-only/")
        assert match.func is probe_view
    finally:
        del sys.modules["apps.bpp.urls_probe"]


def test_history_route_still_resolves():
    """Маршрут ``history/…`` — единственный, объявленный в самом ``urls.py``,
    а не в подмодуле — автодискавери его не задевает."""
    match = resolve("/api/bpp/v1/history/bpp.purchase_request/123")
    assert match.func is bpp_urls.views.object_history

    match_slash = resolve("/api/bpp/v1/history/bpp.purchase_request/123/")
    assert match_slash.func is bpp_urls.views.object_history


@pytest.mark.parametrize("name", ["urls_budget", "urls_requests", "urls_accountable",
                                  "urls_counterparties"])
def test_real_submodules_are_discovered(name):
    assert name in bpp_urls._submodule_names()
