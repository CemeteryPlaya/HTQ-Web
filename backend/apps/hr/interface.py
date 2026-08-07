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


def user_has_permission(user_id: int, permission: str) -> bool:
    """Есть ли у сотрудника явное право его должности.

    Предметные аппки не должны угадывать роль по названию должности
    («Бухгалтер») или импортировать ``Employee``/``Position`` напрямую.
    Они спрашивают эту узкую функцию, а HR остаётся владельцем матрицы
    ``Position.permissions``. Глобальный админ проверяется вызывающей
    аппкой до этого вызова.
    """
    require_service("hr")
    employee = (Employee.objects.filter(user_id=user_id, is_deleted=False)
                .select_related("position").first())
    if employee is None:
        return False
    raw = employee.position.permissions
    if not isinstance(raw, dict):
        return False
    permissions = raw.get("permissions")
    return isinstance(permissions, list) and permission in permissions


def list_departments_brief(limit: int = 500) -> list[dict]:
    """Все отделы разом — для наполнения и админских выборок.

    ``get_departments_brief`` требует список id, которого у вызывающего
    может не быть: команде наполнения apps.tasks нужно разложить проекты
    по РЕАЛЬНЫМ отделам, а какие они — она узнаёт только отсюда.
    """
    require_service("hr")
    return list(
        Department.objects.order_by("path").values(*_BRIEF_FIELDS)[:limit]
    )


def list_employees_brief(limit: int = 500) -> list[dict]:
    """Действующие сотрудники: кто они, в каком отделе и есть ли учётка.

    ``user_id`` отдаётся намеренно: в apps.tasks исполнитель задачи,
    владелец проекта и руководитель объекта — это ИМЕННО user_id (их имена
    резолвит apps.users), а не PK строки Employee. Без этого поля сосед не
    может связать сотрудника с задачей и вынужден был бы лезть в модели hr
    напрямую.
    """
    require_service("hr")
    rows = (
        Employee.objects.filter(is_deleted=False)
        .select_related("position")
        .order_by("last_name", "first_name")
        .values("id", "first_name", "last_name", "email", "user_id",
                "department_id", "position__title", "status")[:limit]
    )
    return [
        {
            "id": row["id"],
            "full_name": f"{row['last_name']} {row['first_name']}".strip(),
            "email": row["email"],
            "user_id": row["user_id"],
            "department_id": row["department_id"],
            "position_title": row["position__title"],
            "status": row["status"],
        }
        for row in rows
    ]


def link_employee_user(employee_id: int, user_id: int) -> bool:
    """Привязать платформенную учётку к карточке сотрудника.

    Запись, а не чтение — единственная в этом модуле. Нужна потому, что
    учётки заводит apps.users (там живёт admin_service с проверками
    уникальности и хешированием пароля), а колонка ``Employee.user_id``
    принадлежит hr, и писать в неё сосед не вправе.

    Возвращает False, если сотрудника нет или учётка уже занята другим —
    ``user_id`` уникален, и молча переклеивать её с одного человека на
    другого нельзя.
    """
    require_service("hr")
    employee = Employee.objects.filter(id=employee_id, is_deleted=False).first()
    if employee is None:
        return False
    if employee.user_id == user_id:
        return True
    if Employee.objects.filter(user_id=user_id).exclude(id=employee_id).exists():
        return False
    employee.user_id = user_id
    employee.save(update_fields=["user_id"])
    return True


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
