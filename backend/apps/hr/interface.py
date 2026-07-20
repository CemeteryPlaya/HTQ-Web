"""Публичный API аппки hr для ДРУГИХ аппок (контракт PLAN.md §7).

Производитель: Поток A. Потребители: apps.tasks (отдел проекта),
apps.approvals (assignee_resolver). Прямой импорт apps.hr.models /
apps.hr.services из другой аппки запрещён и ловится
apps/core/tests/test_app_isolation.py — только через этот модуль.

Сигнатуры зафиксированы (менять только совместно A↔B). Каждая функция
начинается с require_service("hr"): если аппка выключена, вызывающий получает
ServiceDisabled (api_view → 503), а не молчаливый неверный ответ.

Возвращаются простые словари, а не ORM-объекты: сосед не должен зависеть от
внутренней модели hr.
"""
from __future__ import annotations

from apps.core.services import require_service

from apps.hr.models import Department, Employee

_BRIEF_FIELDS = ("id", "name", "path", "is_active")


def get_department_brief(department_id: int) -> dict | None:
    require_service("hr")
    return Department.objects.filter(id=department_id).values(*_BRIEF_FIELDS).first()


def get_departments_brief(department_ids: list[int]) -> list[dict]:
    require_service("hr")
    ids = list(department_ids)
    if not ids:
        return []
    return list(Department.objects.filter(id__in=ids).values(*_BRIEF_FIELDS))


def get_employee_brief(user_id: int) -> dict | None:
    """Карточка сотрудника по user_id из JWT. Мягко удалённые не отдаются."""
    require_service("hr")
    row = (
        Employee.objects.filter(user_id=user_id, is_deleted=False)
        .values("id", "first_name", "last_name", "department_id",
                "position__title", "status")
        .first()
    )
    if row is None:
        return None
    return {
        "id": row["id"],
        "full_name": f"{row['last_name']} {row['first_name']}",
        "department_id": row["department_id"],
        "position_title": row["position__title"],
        "status": row["status"],
    }


def org_ancestors(department_id: int) -> list[dict]:
    """Предки отдела от корня к непосредственному родителю (себя НЕ включая).

    D1 плана: ``path`` — строковый путь вида ``"it.dev.backend"``, а не PG-ltree,
    поэтому предки — это его префиксы (``"it"``, ``"it.dev"``). Берём их одним
    запросом ``path__in``, без рекурсии и без обращения к БД на каждый уровень.
    Порядок результата — от корня вниз (важен для assignee_resolver approvals:
    он поднимается по цепочке согласующих).
    """
    require_service("hr")
    dep = Department.objects.filter(id=department_id).values("path").first()
    if dep is None:
        return []
    parts = dep["path"].split(".")
    prefixes = [".".join(parts[:i]) for i in range(1, len(parts))]
    if not prefixes:
        return []
    by_path = {
        d["path"]: d
        for d in Department.objects.filter(path__in=prefixes).values(*_BRIEF_FIELDS)
    }
    return [by_path[p] for p in prefixes if p in by_path]
