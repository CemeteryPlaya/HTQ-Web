"""Кадровая история (HR-события) — порт
services/hr/app/api/v1/personnel_history.py.

В исходнике логика была inline в роутере (нет отдельного
personnel_history_service.py) — здесь вынесена в сервисный слой по
конвенции остальных перенесённых под-модулей домена (тонкие вьюхи,
логика в apps/hr/services/*).
"""
from __future__ import annotations

from apps.hr.models import Department, Employee, PersonnelHistory, PersonnelHistoryEventType, Position

# Порт EVENT_TYPES исходника (простой tuple) — тот же порядок объявления.
EVENT_TYPES: tuple[str, ...] = tuple(PersonnelHistoryEventType.values)


class PersonnelHistoryNotFound(Exception):
    """404 "PersonnelHistory not found" — порт роутера исходника."""


class InvalidEventType(Exception):
    """400 (НЕ 422 — буквальный порт: роутер исходника поднимает
    ``HTTPException(status_code=400, ...)`` для event_type вне EVENT_TYPES,
    в отличие от pydantic-валидации остальных полей)."""

    def __init__(self, value: str) -> None:
        self.detail = f"event_type must be one of {EVENT_TYPES}"
        super().__init__(self.detail)


def _validate_event_type(value: str) -> str:
    if value not in EVENT_TYPES:
        raise InvalidEventType(value)
    return value


def _resolve(model, id_: int | None, label_attr: str) -> str | None:
    if id_ is None:
        return None
    obj = model.objects.filter(id=id_).first()
    return getattr(obj, label_attr, None) if obj else None


def serialize(ph: PersonnelHistory) -> dict:
    """PersonnelHistoryOut — с резолвленными display-именами (employee_name,
    *_department_name, *_position_title), чтобы клиент не джойнил сам."""
    employee = Employee.objects.filter(id=ph.employee_id).first()
    employee_name = ""
    if employee is not None:
        first = employee.first_name or ""
        last = employee.last_name or ""
        employee_name = (
            f"{last} {first}".strip()
            or getattr(employee, "display_name", None)
            or f"#{employee.id}"
        )
    return {
        "id": ph.id,
        "employee": ph.employee_id,
        "employee_name": employee_name,
        "event_type": ph.event_type,
        "event_date": ph.event_date.isoformat() if ph.event_date else "",
        "from_department": ph.from_department_id,
        "from_department_name": _resolve(Department, ph.from_department_id, "name"),
        "to_department": ph.to_department_id,
        "to_department_name": _resolve(Department, ph.to_department_id, "name"),
        "from_position": ph.from_position_id,
        "from_position_title": _resolve(Position, ph.from_position_id, "title"),
        "to_position": ph.to_position_id,
        "to_position_title": _resolve(Position, ph.to_position_id, "title"),
        "order_number": ph.order_number or "",
        "comment": ph.comment or "",
        # Нет employee_replica в hr-сервисе исходника — клиент отображает
        # "—", если null (буквальный порт).
        "created_by_name": None,
        "created_at": ph.created_at.isoformat() if ph.created_at else "",
    }


def list_history() -> list[PersonnelHistory]:
    return list(PersonnelHistory.objects.order_by("-event_date", "-id"))


def get_history(id: int) -> PersonnelHistory:
    ph = PersonnelHistory.objects.filter(id=id).first()
    if ph is None:
        raise PersonnelHistoryNotFound
    return ph


def create_history(data, *, created_by: int | None) -> PersonnelHistory:
    _validate_event_type(data.event_type)
    return PersonnelHistory.objects.create(
        employee_id=data.employee,
        event_type=data.event_type,
        event_date=data.event_date,
        from_department_id=data.from_department,
        to_department_id=data.to_department,
        from_position_id=data.from_position,
        to_position_id=data.to_position,
        order_number=data.order_number or "",
        comment=data.comment or "",
        created_by=created_by,
    )


def update_history(id: int, data) -> PersonnelHistory:
    ph = get_history(id)
    _validate_event_type(data.event_type)
    ph.employee_id = data.employee
    ph.event_type = data.event_type
    ph.event_date = data.event_date
    ph.from_department_id = data.from_department
    ph.to_department_id = data.to_department
    ph.from_position_id = data.from_position
    ph.to_position_id = data.to_position
    ph.order_number = data.order_number or ""
    ph.comment = data.comment or ""
    ph.save()
    return ph


def delete_history(id: int) -> None:
    ph = get_history(id)
    ph.delete()
