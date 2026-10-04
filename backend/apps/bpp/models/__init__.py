"""Модели модуля БЗО.

Подмодуль пакета подключается сам (мастер-план §2.7, план этапа 2 A,
задача 2): исполнителю достаточно завести файл ``models/<имя>.py`` и
объявить в нём ``__all__`` — этот файл больше не правится вручную под
каждую новую модель, а значит у двух исполнителей нет общей строки
конфликта. ``core`` импортируется первым — от него зависят модели
остальных подмодулей (``BppModel``, ``VersionedModel``), дальше — по
алфавиту, для стабильного и предсказуемого порядка.
"""

from __future__ import annotations

import importlib
import pkgutil

_CORE = "core"


def _submodule_names() -> list[str]:
    """Имена модулей пакета: ``core`` — первым, остальные — по алфавиту."""
    rest = sorted(
        name for _, name, is_pkg in pkgutil.iter_modules(__path__)
        if not is_pkg and not name.startswith("_") and name != _CORE
    )
    return [_CORE, *rest]


for _name in _submodule_names():
    _module = importlib.import_module(f".{_name}", __name__)
    for _symbol in getattr(_module, "__all__", ()):
        globals()[_symbol] = getattr(_module, _symbol)

del _name, _module, _symbol
