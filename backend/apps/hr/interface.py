"""Публичный API аппки hr для ДРУГИХ аппок (контракт PLAN.md §7).

Производитель: Поток A (фаза hr, PLAN.md §6.3). Потребители: apps.tasks
(отдел проекта), apps.approvals (assignee_resolver). Прямой импорт
apps.hr.models / apps.hr.services из другой аппки запрещён и ловится
apps/core/tests/test_app_isolation.py — только через этот модуль.

Скаффолд-заглушки prep 4.0: сигнатуры зафиксированы (менять только совместно
A↔B), тело появится в фазе hr. Каждая функция начинается с require_service("hr"):
если аппка выключена, вызывающий получает ServiceDisabled (api_view → 503),
а не молчаливый неверный ответ.
"""
from __future__ import annotations

from apps.core.services import require_service

_STUB = "apps.hr.interface: заглушка prep 4.0, реализуется в фазе hr (PLAN.md §6.3)"


def get_department_brief(department_id: int) -> dict | None:
    require_service("hr")
    raise NotImplementedError(_STUB)


def get_departments_brief(department_ids: list[int]) -> list[dict]:
    require_service("hr")
    raise NotImplementedError(_STUB)


def get_employee_brief(user_id: int) -> dict | None:
    require_service("hr")
    raise NotImplementedError(_STUB)


def org_ancestors(department_id: int) -> list[dict]:
    require_service("hr")
    raise NotImplementedError(_STUB)
