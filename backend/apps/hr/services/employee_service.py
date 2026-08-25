"""Бизнес-логика сотрудников — порт services/hr/app/services/employee_service.py
(+ repositories/employee_repo.py в части, которую он использовал).

Р2: dramatiq-события ``employee_upserted``/``employee_deleted`` НЕ
портируются — реплик-соседей, слушающих их, больше нет (та же логика, что
и в department_service.py).

Формат ответа (EmployeeOut) переиспользует
``department_service.serialize_employee`` — он уже реализует ровно ту же
форму (нужную и для ``GET /departments/{id}/employees``, и здесь), дублировать
второй сериализатор незачем.
"""
from __future__ import annotations

from django.db import transaction
from django.db.models import Q, Value
from django.db.models.functions import Concat

from apps.hr.models import AuditLog, Department, Employee, EmployeeStatus, Position
from apps.hr.services import audit_service


class EmployeeNotFound(Exception):
    """404 {"detail": "Employee not found"} — вьюха решает точный detail."""


class DepartmentNotFound(Exception):
    """422 {"detail": "Department not found"} — department_id не существует."""


class PositionNotFound(Exception):
    """422 {"detail": "Position not found"} — position_id не существует."""


class EmailAlreadyInUse(Exception):
    """409 {"detail": "Email already in use"}."""


def _assert_department_exists(department_id: int) -> None:
    if not Department.objects.filter(id=department_id).exists():
        raise DepartmentNotFound


def _assert_position_exists(position_id: int) -> None:
    if not Position.objects.filter(id=position_id).exists():
        raise PositionNotFound


def _email_taken(email: str) -> bool:
    # Порт repo.get_by_email: уникальность проверяется только среди активных
    # (мягко удалённые не блокируют повторное использование email).
    return Employee.objects.filter(email=email, is_deleted=False).exists()


# ── чтение ──────────────────────────────────────────────────────────────────

def get_employee(id: int) -> Employee:
    """Порт EmployeeService.get_employee (via repo.get_with_relations)."""
    employee = (
        Employee.objects.filter(id=id, is_deleted=False)
        .select_related("department", "position")
        .first()
    )
    if employee is None:
        raise EmployeeNotFound
    return employee


def get_my_employee(token) -> Employee | None:
    """Порт резолюции ``GET /me/`` в роутере исходника.

    БЕЗ фильтра ``is_deleted`` — сверено буквально с исходником: router
    строит запрос без ``.where(Employee.is_deleted == False)``, в отличие от
    ``get_employee``/``list_employees``. Мягко удалённый (уволенный) сотрудник
    по-прежнему видит собственную анкету через ``/me/``.
    """
    qs = Employee.objects.select_related("department", "position")
    if token.email:
        qs = qs.filter(Q(user_id=token.user_id) | Q(email=token.email))
    else:
        qs = qs.filter(user_id=token.user_id)
    return qs.first()


def list_employees(
    *,
    department_id: int | None = None,
    status: str | None = None,
    search: str | None = None,
    page: int = 1,
    limit: int = 20,
) -> tuple[list[Employee], int]:
    qs = Employee.objects.filter(is_deleted=False).select_related("department", "position")
    if department_id is not None:
        qs = qs.filter(department_id=department_id)
    if status is not None:
        qs = qs.filter(status=status)
    if search:
        pattern = search.strip()
        qs = qs.annotate(_full_name=Concat("first_name", Value(" "), "last_name")).filter(
            Q(first_name__icontains=pattern)
            | Q(last_name__icontains=pattern)
            | Q(middle_name__icontains=pattern)
            | Q(email__icontains=pattern)
            | Q(_full_name__icontains=pattern)
        )

    total = qs.count()
    offset = (page - 1) * limit
    items = list(qs.order_by("last_name")[offset:offset + limit])
    return items, total


def get_history(id: int) -> list[dict]:
    """Порт GET /{id}/history — последние 100 записей hr_auditlog, desc."""
    logs = (
        AuditLog.objects.filter(entity_type="employee", entity_id=id)
        .order_by("-created_at")[:100]
    )
    return [
        {
            "id": log.id,
            "action": log.action,
            "old_values": log.old_values,
            "new_values": log.new_values,
            "changed_by": log.changed_by,
            "created_at": log.created_at.isoformat(),
        }
        for log in logs
    ]


# ── запись ──────────────────────────────────────────────────────────────────

@transaction.atomic
def create_employee(data, *, changed_by_id: int) -> Employee:
    _assert_department_exists(data.department_id)
    _assert_position_exists(data.position_id)
    if _email_taken(data.email):
        raise EmailAlreadyInUse

    employee = Employee.objects.create(**data.model_dump())
    audit_service.log(
        entity_type="employee",
        entity_id=employee.id,
        action="create",
        new_values=data.model_dump(mode="json"),
        changed_by=changed_by_id,
    )
    return get_employee(employee.id)


@transaction.atomic
def update_employee(id: int, data, *, changed_by_id: int) -> Employee:
    employee = get_employee(id)
    patch = data.model_dump(exclude_none=True)

    # Идентичность связанного сотрудника принадлежит его аккаунту (спека
    # 2026-08-25 §3): такие поля не пишутся в строку, а уходят заявкой, и
    # дальше по коду patch содержит только трудовые поля. У «скелета» без
    # user_id владельца нет — capture вернёт патч нетронутым.
    from apps.hr.services import identity_request_service

    patch, identity_request = identity_request_service.capture(
        employee, patch, actor_id=changed_by_id,
    )

    if "department_id" in patch:
        _assert_department_exists(patch["department_id"])
    if "position_id" in patch:
        _assert_position_exists(patch["position_id"])
    if "email" in patch and patch["email"] != employee.email and _email_taken(patch["email"]):
        raise EmailAlreadyInUse

    old_values = {field: getattr(employee, field) for field in patch}
    for field, value in patch.items():
        setattr(employee, field, value)
    if patch:
        employee.save()

    audit_service.log(
        entity_type="employee",
        entity_id=id,
        action="update",
        old_values={k: str(v) for k, v in old_values.items()},
        new_values={
            **{k: str(v) for k, v in patch.items()},
            # След заявки в кадровом журнале: без него правка идентичности
            # выглядела бы как «ничего не изменилось».
            **({"identity_request_id": str(identity_request.id)}
               if identity_request is not None else {}),
        },
        changed_by=changed_by_id,
    )
    return get_employee(id)


@transaction.atomic
def delete_employee(id: int, *, changed_by_id: int) -> None:
    """Мягкое удаление — порт repo.soft_delete: is_deleted=True И
    status='terminated' (обе колонки, не только is_deleted)."""
    employee = get_employee(id)
    employee.is_deleted = True
    employee.status = EmployeeStatus.TERMINATED
    employee.save()
    audit_service.log(
        entity_type="employee",
        entity_id=id,
        action="delete",
        changed_by=changed_by_id,
    )


@transaction.atomic
def transfer_employee(id: int, data, *, changed_by_id: int) -> Employee:
    """Порт transfer_employee. ``data.effective_date`` намеренно игнорируется
    (буквальное поведение исходника — EmployeeTransfer его несёт, но
    employee_service его нигде не читает)."""
    employee = get_employee(id)
    _assert_department_exists(data.department_id)
    if data.position_id:
        _assert_position_exists(data.position_id)

    old_department_id = employee.department_id
    employee.department_id = data.department_id
    if data.position_id:
        employee.position_id = data.position_id
    employee.save()

    audit_service.log(
        entity_type="employee",
        entity_id=id,
        action="update",
        old_values={"department_id": str(old_department_id)},
        new_values={"department_id": str(data.department_id)},
        changed_by=changed_by_id,
    )
    return get_employee(id)
