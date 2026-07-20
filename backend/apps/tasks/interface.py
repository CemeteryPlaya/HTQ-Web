"""Публичный API аппки tasks для ДРУГИХ аппок (контракт PLAN.md §7).

Производитель: Поток B (фаза task, PLAN.md §6.1). Явных потребителей пока нет
(get_task_brief — «по необходимости»); заглушка оставлена для единообразия
скаффолда и как готовая точка расширения. Прямой импорт apps.tasks.* из
другой аппки запрещён (test_app_isolation.py) — только через этот модуль.

Скаффолд-заглушка prep 4.0: тело появится в фазе task. Функция начинается с
require_service("tasks").
"""
from __future__ import annotations

from apps.core.services import require_service

_STUB = "apps.tasks.interface: заглушка prep 4.0, реализуется в фазе task (PLAN.md §6.1)"


def get_task_brief(task_id: int) -> dict | None:
    require_service("tasks")
    raise NotImplementedError(_STUB)
