"""Маршруты /api/bpp/v1/.

Подмодуль держит маршруты в ``urls_<подмодуль>.py`` и вьюхи в
``views_<подмодуль>.py`` (импорт ``from . import views_<подмодуль> as
views``) — так у двух исполнителей нет общего файла, а сторожа прав
(``apps/access/tests/test_gate.py``) видят пару ``urls_x.py`` ↔
``views_x.py``.

Подключение — автодискавери (план этапа 2 A, задача 2, то же решение, что
у ``models/__init__.py``): любой файл ``urls_*.py`` пакета подключается
сам, без явной строки ``include`` на каждый новый подмодуль. Порядок — по
алфавиту имени подмодуля, он не значим (пути разных подмодулей не
пересекаются).
"""

from __future__ import annotations

import importlib
import pkgutil

from django.urls import include, path

from . import views

_PREFIX = "urls_"
_package = importlib.import_module(__package__)


def _submodule_names() -> list[str]:
    """Имена модулей ``urls_<подмодуль>.py`` пакета — по алфавиту."""
    return sorted(
        name for _, name, is_pkg in pkgutil.iter_modules(_package.__path__)
        if not is_pkg and name.startswith(_PREFIX)
    )


def _submodule_patterns() -> list:
    return [path("", include(f"{__package__}.{name}")) for name in _submodule_names()]


urlpatterns = [
    path("history/<str:object_type>/<str:object_id>", views.object_history),
    path("history/<str:object_type>/<str:object_id>/", views.object_history),
    path("me", views.me),
    path("me/", views.me),
    *_submodule_patterns(),
]
