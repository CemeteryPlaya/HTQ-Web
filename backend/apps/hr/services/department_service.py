"""Бизнес-логика отделов — порт services/hr/app/services/department_service.py
(+ repositories/department_repo.py).

Решения, зафиксированные при переносе (docs/plans/2026-07-20-hr-domain.md):

* **D1** — ``path`` это обычная строка ("it.dev.backend"), не PG-ltree.
  Иерархия считается по префиксам, как и в исходнике (там тоже LIKE, а не ltree).
* **Р2** — dramatiq-события ``department_upserted``/``department_deleted``
  НЕ портируются: реплик соседей больше нет, соседи ходят через
  ``apps.hr.interface``.
* Две особенности исходника сохранены намеренно (это контракт, а не баг,
  который чинят молча при переносе):
  ``get_children`` из-за ``LIKE 'parent.%'`` отдаёт ВЕСЬ поддерев, а не
  прямых детей (докстринг исходника этому противоречит), а
  ``get_employees`` отдаёт сотрудников ВКЛЮЧАЯ мягко удалённых.
"""
from __future__ import annotations

import re
import time
import uuid

from django.db import transaction
from django.db.models import Q

from apps.hr.models import Department, Employee, PMOMember, Position, ReportingRelation

# Транслитерация из исходника (department_service.create_department), символ
# в символ — от неё зависят уже существующие пути отделов.
_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


class DepartmentNotFound(Exception):
    """Отдел не найден — вьюха превращает в 404 {"detail": "Department not found"}."""


class DepartmentHasDependents(Exception):
    """409: к отделу привязаны записи, а cascade не запрошен.

    Несёт СТРУКТУРНЫЙ detail (объект, не строка) — фронт по нему рисует
    точное подтверждение и повторяет запрос с cascade=true.
    """

    def __init__(self, department: Department, blockers: dict) -> None:
        self.detail = {
            "code": "department_has_dependents",
            "message": (
                f"К подразделению «{department.name}» привязаны другие записи. "
                "Подтвердите каскадное удаление."
            ),
            "department": {"id": department.id, "name": department.name},
            "blockers": blockers,
        }
        super().__init__(self.detail["message"])


def slugify_name(name: str) -> str:
    slug = "".join(_TRANSLIT.get(c, c) for c in name.lower())
    slug = re.sub(r"[^a-z0-9]+", "_", slug).strip("_")
    return slug or f"dept_{str(uuid.uuid4())[:8]}"


# ── сериализаторы (формы из schemas/department.py) ──────────────────────────

def _position_short(pos: Position) -> dict:
    return {
        "id": pos.id, "title": pos.title, "department_id": pos.department_id,
        "grade": pos.grade, "weight": pos.weight, "level": pos.level,
        "is_system": pos.is_system,
    }


def serialize(dep: Department) -> dict:
    """DepartmentOut."""
    return {
        "id": dep.id,
        "name": dep.name,
        "path": dep.path,
        "description": dep.description,
        "manager_id": dep.manager_id,
        "is_active": dep.is_active,
        "created_at": dep.created_at.isoformat(),
        "updated_at": dep.updated_at.isoformat(),
    }


def serialize_with_positions(dep: Department) -> dict:
    """DepartmentWithPositions — позиции по weight (order_by связи исходника)."""
    out = serialize(dep)
    out["positions"] = [_position_short(p) for p in dep.positions.all()]
    return out


def serialize_employee(emp: Employee) -> dict:
    """EmployeeOut (schemas/employee.py) — с вложенными department/position."""
    return {
        "id": emp.id,
        "user_id": emp.user_id,
        "first_name": emp.first_name,
        "last_name": emp.last_name,
        "middle_name": emp.middle_name,
        "email": emp.email,
        "phone": emp.phone,
        "department_id": emp.department_id,
        "position_id": emp.position_id,
        "hire_date": emp.hire_date.isoformat(),
        "termination_date": emp.termination_date.isoformat() if emp.termination_date else None,
        "status": emp.status,
        "avatar_url": emp.avatar_url,
        "bio": emp.bio,
        "department": {"id": emp.department.id, "name": emp.department.name,
                       "path": emp.department.path} if emp.department_id else None,
        "position": _position_short(emp.position) if emp.position_id else None,
        "created_at": emp.created_at.isoformat(),
        "updated_at": emp.updated_at.isoformat(),
    }


# ── чтение ──────────────────────────────────────────────────────────────────

def get_department(department_id: int) -> Department:
    dep = Department.objects.filter(id=department_id).first()
    if dep is None:
        raise DepartmentNotFound
    return dep


def list_departments() -> list[dict]:
    qs = (Department.objects.filter(is_active=True)
          .prefetch_related("positions")     # без N+1, как selectinload в исходнике
          .order_by("path"))
    return [serialize_with_positions(d) for d in qs]


def get_tree() -> list[dict]:
    """Плоский список активных отделов → вложенное дерево по префиксам path."""
    departments = list(Department.objects.filter(is_active=True).order_by("path"))
    nodes = {d.id: {**serialize(d), "children": []} for d in departments}
    by_path = {d.path: d for d in departments}
    roots: list[dict] = []
    for dep in departments:
        parent_path = ".".join(dep.path.split(".")[:-1])
        parent = by_path.get(parent_path)
        if parent is not None and parent.id in nodes:
            nodes[parent.id]["children"].append(nodes[dep.id])
        else:
            roots.append(nodes[dep.id])
    return roots


def get_children(department_id: int) -> list[dict]:
    dep = get_department(department_id)
    qs = (Department.objects.filter(path__startswith=f"{dep.path}.", is_active=True)
          .order_by("name"))
    return [serialize(d) for d in qs]


def get_employees(department_id: int) -> list[dict]:
    dep = get_department(department_id)
    qs = dep.employees.select_related("department", "position").order_by("id")
    return [serialize_employee(e) for e in qs]


# ── запись ──────────────────────────────────────────────────────────────────

def create_department(data) -> Department:
    path = data.path
    if not path:
        slug = slugify_name(data.name)
        if data.parent_id:
            parent = get_department(data.parent_id)
            path = f"{parent.path}.{slug}"
        else:
            path = slug
    if Department.objects.filter(path=path).exists():
        path = f"{path}_{int(time.time())}"

    payload = data.model_dump(exclude={"parent_id"}, exclude_none=True)
    payload["path"] = path
    return Department.objects.create(**payload)


def update_department(department_id: int, data) -> Department:
    dep = get_department(department_id)
    patch = data.model_dump(exclude_none=True)
    for field, value in patch.items():
        setattr(dep, field, value)
    if patch:
        dep.save()
    return dep


@transaction.atomic
def delete_department(department_id: int, *, cascade: bool = False) -> None:
    dep = get_department(department_id)

    subtree_ids = list(
        Department.objects.filter(path__startswith=f"{dep.path}.").values_list("id", flat=True)
    )
    blockers = {
        "sub_departments": len(subtree_ids),
        "positions": Position.objects.filter(department_id=dep.id).count(),
        # мягко удалённые не блокируют — как в исходнике
        "employees": Employee.objects.filter(department_id=dep.id, is_deleted=False).count(),
    }

    if any(blockers.values()) and not cascade:
        raise DepartmentHasDependents(dep, blockers)

    if cascade and any(blockers.values()):
        dept_ids = [dep.id, *subtree_ids]
        employee_ids = list(
            Employee.objects.filter(department_id__in=dept_ids).values_list("id", flat=True)
        )

        # 1. Drop reporting relations — буквально как в исходнике
        # (department_service.py, шаг «1. Drop reporting relations»): любая
        # связь подчинения, где ЛИБО superior_position, ЛИБО
        # subordinate_position входит в удаляемое поддерево, чистится ДО
        # удаления самих позиций. Django FK (on_delete=CASCADE) уже сделал бы
        # то же самое молча при Position.delete() ниже — здесь оставлено явно,
        # чтобы порт совпадал с шагами исходника буквально (а не полагался на
        # побочный эффект каскада), и не сломался, если FK-поведение когда-то
        # изменится.
        position_ids = list(
            Position.objects.filter(department_id__in=dept_ids).values_list("id", flat=True)
        )
        if position_ids:
            ReportingRelation.objects.filter(
                Q(superior_position_id__in=position_ids)
                | Q(subordinate_position_id__in=position_ids)
            ).delete()

        # 2. Drop PMO memberships of in-scope employees — буквально как в
        # исходнике (department_service.py, шаг «2. Drop PMO memberships»:
        # ``sa_delete(PMOMember).where(PMOMember.employee_id.in_(employee_ids))``),
        # ПЕРЕД удалением самих сотрудников ниже. Django FK
        # (PMOMember.employee, on_delete=CASCADE) уже сделал бы то же самое
        # молча при Employee.delete() ниже — оставлено явно по тому же
        # принципу, что и шаг 1 выше (буквальный паритет шагов, а не
        # полагание на побочный эффект каскада).
        if employee_ids:
            PMOMember.objects.filter(employee_id__in=employee_ids).delete()

        # Обнуляем manager_id: и у отделов поддерева, и у любых других
        # отделов, чей руководитель попадает под удаление.
        Department.objects.filter(id__in=dept_ids).update(manager=None)
        if employee_ids:
            Department.objects.filter(manager_id__in=employee_ids).update(manager=None)
            Employee.objects.filter(id__in=employee_ids).delete()
        Position.objects.filter(department_id__in=dept_ids).delete()

        # Дочерние — от самых глубоких, чтобы порядок не зависел от FK.
        children = list(Department.objects.filter(id__in=subtree_ids))
        children.sort(key=lambda d: -len(d.path.split(".")))
        for child in children:
            child.delete()

    dep.delete()
