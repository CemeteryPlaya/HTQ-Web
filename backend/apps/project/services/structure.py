"""Проектная структура: справочник ролей, места и назначения сотрудников.

Спек — docs/plans/2026-10-06-project-structure-spec.md (подпроект 1). Своя у
каждого проекта и не связана с кадровой схемой ``hr``: сотрудник —
``Employee.id`` голым числом, ФИО и статус — через ``hr.interface``.

Все записи по проекту идут под блокировкой его строки (``select_for_update``):
лимит плана и правила дерева проверяются чтением соседних строк, и две
параллельные правки одного дерева без очереди обе прошли бы проверку.
"""

from __future__ import annotations

from datetime import date

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from apps.hr import interface as hr
from apps.project.models import (Project, ProjectAssignment, ProjectPart, ProjectRole,
                                 ProjectSlot)
from apps.project.services import projects


class StructureError(Exception):
    """Нарушено правило дерева, плана или дат (409 ``E-PRJ-05``)."""


class EmployeeError(Exception):
    """Сотрудник не найден среди действующих (422 ``E-PRJ-06``)."""


class RoleError(Exception):
    """Конфликт справочника ролей (409 ``E-PRJ-07``)."""


def _today() -> date:
    return timezone.localdate()


def _lock(project_id) -> None:
    Project.objects.select_for_update().filter(pk=project_id).first()


def _active_on(assignments, on: date):
    return assignments.filter(Q(date_to__isnull=True) | Q(date_to__gte=on), date_from__lte=on)


def _overlapping(assignments, date_from: date, date_to: date | None):
    rows = assignments.filter(Q(date_to__isnull=True) | Q(date_to__gte=date_from))
    return rows if date_to is None else rows.filter(date_from__lte=date_to)


# ── Справочник ролей ────────────────────────────────────────────────────────

def role_out(role: ProjectRole) -> dict:
    return {"id": role.id, "name": role.name, "level": role.level,
            "default_part": role.default_part, "sort_order": role.sort_order,
            "is_active": role.is_active}


def list_roles(*, active_only: bool = False) -> list[dict]:
    rows = ProjectRole.objects.all()
    if active_only:
        rows = rows.filter(is_active=True)
    return [role_out(r) for r in rows]


def _save_role(role: ProjectRole) -> None:
    try:
        with transaction.atomic():
            role.save()
    except IntegrityError as exc:
        raise RoleError(f"Роль «{role.name}» уже есть в справочнике.") from exc


def create_role(*, name: str, level: int, default_part: str = ProjectPart.OFFICE,
                sort_order: int = 0) -> dict:
    role = ProjectRole(name=name.strip(), level=level, default_part=default_part,
                       sort_order=sort_order)
    _save_role(role)
    return role_out(role)


@transaction.atomic
def update_role(role: ProjectRole, **fields) -> dict:
    role = ProjectRole.objects.select_for_update().get(pk=role.pk)
    level = fields.get("level")
    if level is not None and level != role.level and role.slots.exists():
        # Уровень держит правило «руководитель строго выше» уже построенных
        # деревьев: смена уровня молча сломала бы их.
        raise RoleError("Уровень роли, которая уже стоит на местах проектов, менять нельзя — "
                        "заведите новую роль.")
    for key in ("name", "level", "default_part", "sort_order", "is_active"):
        if fields.get(key) is not None:
            setattr(role, key, fields[key].strip() if key == "name" else fields[key])
    _save_role(role)
    return role_out(role)


@transaction.atomic
def delete_role(role: ProjectRole) -> None:
    if role.slots.exists():
        raise RoleError("Роль уже стоит на местах проектов — её можно только выключить.")
    role.delete()


# ── Места ───────────────────────────────────────────────────────────────────

def _parent(project: Project, level: int, parent_id) -> ProjectSlot | None:
    """Руководитель места: открытое место того же проекта строго выше по уровню.

    Цикл при строгом убывании уровня вверх по дереву невозможен, поэтому
    отдельного обхода нет: «подчинённого назначить руководителем» отвергает
    правило уровня."""
    if parent_id is None:
        if level != 1:
            raise StructureError("Без руководителя может быть только место уровня L1.")
        return None
    parent = (ProjectSlot.objects.select_related("role")
              .filter(pk=parent_id, project=project).first())
    if parent is None:
        raise StructureError("Руководитель — место этого же проекта.")
    if parent.closed_on is not None:
        raise StructureError("Место руководителя закрыто.")
    if parent.role.level >= level:
        raise StructureError(f"Руководитель должен стоять выше по уровню: L{parent.role.level} "
                             f"не выше L{level}.")
    return parent


@transaction.atomic
def create_slot(project: Project, *, role_id: int, actor_id: int, parent_id=None,
                part: str | None = None, title: str = "",
                planned_headcount: int = 1) -> ProjectSlot:
    _lock(project.pk)
    role = ProjectRole.objects.filter(pk=role_id, is_active=True).first()
    if role is None:
        raise StructureError("Роль не найдена в справочнике или выключена.")
    return ProjectSlot.objects.create(
        project=project, role=role, part=part or role.default_part, title=title.strip(),
        parent=_parent(project, role.level, parent_id),
        planned_headcount=planned_headcount, created_by=actor_id)


def _check_close(slot: ProjectSlot, closed_on: date) -> None:
    if slot.assignments.filter(Q(date_to__isnull=True) | Q(date_to__gte=closed_on)).exists():
        raise StructureError("На месте есть люди на дату закрытия — сначала снимите их датой "
                             "раньше закрытия.")
    if slot.children.filter(Q(closed_on__isnull=True) | Q(closed_on__gt=closed_on)).exists():
        raise StructureError("У места есть открытые подчинённые места — сначала закройте их "
                             "или переподчините.")


@transaction.atomic
def update_slot(slot: ProjectSlot, *, actor_id: int, **fields) -> ProjectSlot:
    """Ключи ``fields``: ``parent_id`` (присутствие ключа с ``None`` — «без
    руководителя»), ``part``, ``title``, ``planned_headcount``, ``closed_on``."""
    _lock(slot.project_id)
    slot = ProjectSlot.objects.select_related("role", "project").get(pk=slot.pk)
    if slot.closed_on is not None:
        raise StructureError("Место закрыто — его не правят, заводят новое.")
    if "parent_id" in fields:
        slot.parent = _parent(slot.project, slot.role.level, fields["parent_id"])
    if fields.get("part") is not None:
        slot.part = fields["part"]
    if fields.get("title") is not None:
        slot.title = fields["title"].strip()
    planned = fields.get("planned_headcount")
    if planned is not None:
        busy = _active_on(slot.assignments, _today()).count()
        if planned < busy:
            raise StructureError(f"Сейчас на месте {busy} чел. — план не может быть меньше.")
        slot.planned_headcount = planned
    if fields.get("closed_on") is not None:
        _check_close(slot, fields["closed_on"])
        slot.closed_on = fields["closed_on"]
    slot.save()
    return slot


# ── Назначения ──────────────────────────────────────────────────────────────

def _check_assignment(slot: ProjectSlot, employee_id: int, date_from: date,
                      date_to: date | None, exclude_id=None) -> None:
    if date_to is not None and date_to < date_from:
        raise StructureError("Дата окончания назначения раньше даты начала.")
    if slot.closed_on is not None and (date_to is None or date_to >= slot.closed_on):
        raise StructureError(f"Место закрыто с {slot.closed_on:%d.%m.%Y}.")
    others = slot.assignments.exclude(pk=exclude_id)
    if _overlapping(others.filter(employee_id=employee_id), date_from, date_to).exists():
        raise StructureError("Этот сотрудник уже на этом месте в эти даты.")
    rows = list(_overlapping(others, date_from, date_to))
    for point in {date_from} | {a.date_from for a in rows if a.date_from > date_from}:
        busy = sum(1 for a in rows
                   if a.date_from <= point and (a.date_to is None or a.date_to >= point))
        if busy >= slot.planned_headcount:
            raise StructureError(f"На месте уже {busy} из {slot.planned_headcount} по плану на "
                                 f"{point:%d.%m.%Y} — сначала увеличьте план.")


@transaction.atomic
def create_assignment(slot: ProjectSlot, *, employee_id: int, date_from: date, actor_id: int,
                      date_to: date | None = None) -> ProjectAssignment:
    _lock(slot.project_id)
    slot = ProjectSlot.objects.select_related("project").get(pk=slot.pk)
    if slot.closed_on is not None:
        raise StructureError("Место закрыто — на него не назначают.")
    found = hr.employees_brief([employee_id])
    if not found or not found[0]["active"]:
        raise EmployeeError("Сотрудник не найден среди действующих сотрудников компании.")
    _check_assignment(slot, employee_id, date_from, date_to)
    assignment = ProjectAssignment.objects.create(slot=slot, employee_id=employee_id,
                                                  date_from=date_from, date_to=date_to,
                                                  created_by=actor_id)
    if found[0]["user_id"]:
        # Видеть проект и его доску задач (спек §2.3); снятие с места
        # участника не убирает — его могли добавить вручную.
        projects.add_member(slot.project, found[0]["user_id"], actor_id=actor_id)
    return assignment


@transaction.atomic
def update_assignment(assignment: ProjectAssignment, *, actor_id: int,
                      **fields) -> ProjectAssignment:
    """Ключи ``fields``: ``date_from``, ``date_to`` (присутствие ключа с
    ``None`` — «бессрочно»)."""
    _lock(assignment.slot.project_id)
    assignment = ProjectAssignment.objects.select_related("slot").get(pk=assignment.pk)
    date_from = fields.get("date_from") or assignment.date_from
    date_to = fields["date_to"] if "date_to" in fields else assignment.date_to
    _check_assignment(assignment.slot, assignment.employee_id, date_from, date_to,
                      exclude_id=assignment.pk)
    assignment.date_from, assignment.date_to = date_from, date_to
    assignment.save()
    return assignment


@transaction.atomic
def delete_assignment(assignment: ProjectAssignment, *, today: date | None = None) -> None:
    if assignment.date_from <= (today or _today()):
        raise StructureError("Начавшееся назначение не удаляют — снимите сотрудника датой.")
    assignment.delete()


# ── Чтение ──────────────────────────────────────────────────────────────────

def structure(project: Project, on: date) -> list[dict]:
    """Места, открытые на дату ``on``, с назначениями, действующими на неё.
    ФИО — одним запросом к ``hr.interface`` на всё дерево."""
    slots = list(project.slots.select_related("role")
                 .filter(Q(closed_on__isnull=True) | Q(closed_on__gt=on))
                 .order_by("role__level", "role__sort_order", "created_at"))
    assignments = list(_active_on(ProjectAssignment.objects.filter(slot__in=slots), on)
                       .order_by("date_from", "created_at"))
    people = {e["id"]: e for e in hr.employees_brief(sorted({a.employee_id for a in assignments}))}
    by_slot: dict = {}
    for a in assignments:
        person = people.get(a.employee_id)
        by_slot.setdefault(a.slot_id, []).append({
            "id": str(a.id), "employee_id": a.employee_id,
            "full_name": person["full_name"] if person else f"Сотрудник №{a.employee_id}",
            "position_title": person["position_title"] if person else "",
            "date_from": a.date_from, "date_to": a.date_to,
            "dismissed": not (person and person["active"]),
        })
    return [{
        "id": str(s.id),
        "role": {"id": s.role.id, "name": s.role.name, "level": s.role.level},
        "part": s.part, "title": s.title,
        "parent_id": str(s.parent_id) if s.parent_id else None,
        "planned_headcount": s.planned_headcount,
        "actual_headcount": len(by_slot.get(s.id, [])),
        "closed_on": s.closed_on,
        "assignments": by_slot.get(s.id, []),
    } for s in slots]
