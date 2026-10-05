"""Временные исполнители должностей (мастер-план БЗО, B1.1, D-22).

Кто ИСПОЛНЯЕТ должность на период — в дополнение к её держателям. Движок
согласования узнаёт о них через ``hr.interface.resolve_position_users``:
временный исполнитель получает этапы, которые активируются, пока действует
назначение. Уже созданные задачи назначение не трогает.

Правила, которые БД не выражает сама:
- исполняет только тот, кто может согласовать: действующий сотрудник, не
  удалённый, со связанной учётной записью. Иначе назначение отправило бы
  документ к человеку, который его не увидит;
- исполнять можно только действующую должность — у неактивной нет этапов.

Границы периода ВКЛЮЧИТЕЛЬНЫЕ: назначение «с 1 по 14 октября» действует и
1-го, и 14-го.
"""

from __future__ import annotations

import datetime as dt

from apps.hr.models import ActingAssignment, Employee, EmployeeStatus, Position


class ActingError(Exception):
    """База ошибок домена. ``status``/``detail`` читает слой HTTP."""

    status = 400
    detail = "Ошибка назначения временного исполнителя."

    def __init__(self, detail: str | None = None) -> None:
        if detail:
            self.detail = detail
        super().__init__(self.detail)


class ActingNotFound(ActingError):
    status = 404
    detail = "Назначение временного исполнителя не найдено."


class ActingInvalid(ActingError):
    status = 422


def serialize(row: ActingAssignment) -> dict:
    """ActingAssignmentOut. Названия должности и ФИО кладутся рядом с id:
    список назначений читают люди, и второй запрос ради подписи не нужен."""
    return {
        "id": row.id,
        "position_id": row.position_id,
        "position_title": row.position.title,
        "employee_id": row.employee_id,
        "employee_name": _employee_name(row.employee),
        "user_id": row.employee.user_id,
        "date_from": row.date_from.isoformat(),
        "date_to": row.date_to.isoformat(),
        "basis": row.basis,
        "assigned_by_id": row.assigned_by_id,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


def _employee_name(employee: Employee) -> str:
    parts = [employee.last_name, employee.first_name, getattr(employee, "middle_name", "")]
    return " ".join(part for part in parts if part).strip() or f"Сотрудник #{employee.pk}"


def list_assignments(*, position_id: int | None = None, employee_id: int | None = None,
                     active_on: dt.date | None = None) -> list[ActingAssignment]:
    """Назначения с фильтрами; ``active_on`` — только действующие на дату."""
    qs = ActingAssignment.objects.select_related("position", "employee")
    if position_id is not None:
        qs = qs.filter(position_id=position_id)
    if employee_id is not None:
        qs = qs.filter(employee_id=employee_id)
    if active_on is not None:
        qs = qs.filter(date_from__lte=active_on, date_to__gte=active_on)
    return list(qs)


def get_or_404(assignment_id: int) -> ActingAssignment:
    row = (ActingAssignment.objects.select_related("position", "employee")
           .filter(pk=assignment_id).first())
    if row is None:
        raise ActingNotFound()
    return row


def _check_position(position_id: int) -> Position:
    position = Position.objects.filter(pk=position_id).first()
    if position is None:
        raise ActingNotFound("Должность не найдена.")
    if not position.is_active:
        raise ActingInvalid(
            f"Должность «{position.title}» неактивна — исполнять её некому и "
            f"нечего. Активируйте должность или выберите другую.")
    return position


def _check_employee(employee_id: int) -> Employee:
    employee = Employee.objects.filter(pk=employee_id).first()
    if employee is None:
        raise ActingNotFound("Сотрудник не найден.")
    name = _employee_name(employee)
    if employee.is_deleted or employee.status != EmployeeStatus.ACTIVE:
        raise ActingInvalid(
            f"{name} не работает в компании — назначить его временным "
            f"исполнителем нельзя. Выберите действующего сотрудника.")
    if employee.user_id is None:
        raise ActingInvalid(
            f"У сотрудника {name} нет учётной записи — документы на согласование "
            f"он не увидит. Свяжите его с учётной записью и повторите.")
    return employee


def _check_dates(date_from: dt.date, date_to: dt.date) -> None:
    if date_to < date_from:
        raise ActingInvalid(
            "Дата окончания раньше даты начала. Укажите период, в котором "
            "сотрудник исполняет должность.")


def create(*, position_id: int, employee_id: int, date_from: dt.date, date_to: dt.date,
           basis: str, assigned_by_id: int | None) -> ActingAssignment:
    _check_position(position_id)
    _check_employee(employee_id)
    _check_dates(date_from, date_to)
    row = ActingAssignment.objects.create(
        position_id=position_id, employee_id=employee_id, date_from=date_from,
        date_to=date_to, basis=basis, assigned_by_id=assigned_by_id)
    return get_or_404(row.pk)


def update(assignment_id: int, **fields) -> ActingAssignment:
    """Патч: поля, которых нет в ``fields``, не трогаются."""
    row = get_or_404(assignment_id)
    if "position_id" in fields:
        _check_position(fields["position_id"])
    if "employee_id" in fields:
        _check_employee(fields["employee_id"])
    date_from = fields.get("date_from", row.date_from)
    date_to = fields.get("date_to", row.date_to)
    _check_dates(date_from, date_to)
    for name in ("position_id", "employee_id", "date_from", "date_to", "basis"):
        if name in fields:
            setattr(row, name, fields[name])
    row.save()
    return get_or_404(row.pk)


def delete(assignment_id: int) -> None:
    get_or_404(assignment_id).delete()


def active_user_ids(position_ids, on_date: dt.date) -> dict[int, list[int]]:
    """Учётные записи временных исполнителей должностей на дату:
    ``{position_id: [user_id, …]}``. Только действующие сотрудники
    действующих должностей; активность САМОЙ учётной записи проверяет
    вызывающий (``hr.interface`` — через ``apps.users``)."""
    ids = list(dict.fromkeys(position_ids))
    out: dict[int, list[int]] = {position_id: [] for position_id in ids}
    if not ids:
        return out
    rows = (ActingAssignment.objects
            .filter(position_id__in=ids, date_from__lte=on_date, date_to__gte=on_date,
                    position__is_active=True, employee__status=EmployeeStatus.ACTIVE,
                    employee__is_deleted=False, employee__user_id__isnull=False)
            .order_by("date_from", "id")
            .values_list("position_id", "employee__user_id"))
    for position_id, user_id in rows:
        if user_id not in out[position_id]:
            out[position_id].append(user_id)
    return out
