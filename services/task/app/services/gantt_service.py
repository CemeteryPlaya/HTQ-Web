"""Aggregation for the two Gantt views.

- ``reports_gantt``  — flat list of selected tasks (report on planned/actual dates).
- ``resource_gantt`` — tasks grouped by resource row (employees + equipment).

Kept as plain functions; routes call them. No cross-schema joins — everything
lives in the task domain (tasks / task_users / task_departments / task_equipment
/ task_assignments).
"""

from datetime import date

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.assignment import TaskAssignment
from app.models.department_replica import Department
from app.models.equipment import Equipment
from app.models.task import Status, Task
from app.models.user_replica import User

# Terminal statuses stamp ``completed_at`` (see Task model) — the bar ends there.
_DONE = (Status.DONE, Status.CANCELLED)
# Coarse progress per status (no time-tracking yet) — good enough for visuals.
_PROGRESS = {
    Status.BACKLOG: 0.0,
    Status.TODO: 0.0,
    Status.IN_PROGRESS: 0.4,
    Status.BLOCKED: 0.4,
    Status.IN_REVIEW: 0.75,
    Status.DONE: 1.0,
    Status.CANCELLED: 1.0,
}


def _progress(status: Status) -> float:
    return _PROGRESS.get(status, 0.0)


def _end_date(task: Task) -> date | None:
    """Bar end: actual completion for done/closed, else the planned due date."""
    if task.status in _DONE and task.completed_at:
        return task.completed_at.date()
    return task.due_date or (task.completed_at.date() if task.completed_at else None)


def _start_date(task: Task) -> date | None:
    return task.start_date or task.due_date


async def reports_gantt(
    db: AsyncSession,
    ids: list[int] | None,
    statuses: list[str] | None,
) -> dict:
    stmt = select(Task).where(Task.is_deleted.is_(False))
    if ids:
        stmt = stmt.where(Task.id.in_(ids))
    if statuses:
        stmt = stmt.where(Task.status.in_(statuses))
    stmt = stmt.order_by(Task.start_date.nulls_last(), Task.id)

    tasks = (await db.execute(stmt)).scalars().all()
    return {
        "tasks": [
            {
                "id": str(t.id),
                "key": t.key,
                "text": t.summary,
                "start_date": _start_date(t),
                "end_date": _end_date(t),
                "progress": _progress(t.status),
                "status": str(t.status),
                "parent": str(t.parent_id) if t.parent_id else None,
                "assignees": [],
            }
            for t in tasks
        ]
    }


async def resource_gantt(
    db: AsyncSession,
    dt_from: date,
    dt_to: date,
    kinds: set[str],
    department_id: int | None = None,
    search: str | None = None,
) -> dict:
    eff_start = func.coalesce(Task.start_date, Task.due_date)
    eff_end = func.coalesce(Task.due_date, Task.start_date)
    overlap = and_(
        or_(Task.start_date.isnot(None), Task.due_date.isnot(None)),
        eff_start <= dt_to,
        eff_end >= dt_from,
    )

    rows: dict[str, dict] = {}
    seen: set[tuple[str, str]] = set()  # (resource_id, task_id) — de-dupe across sources
    needle = (search or "").strip().lower()

    def add(rid: str, kind: str, name: str, meta: dict, task: Task, allocation: int) -> None:
        if needle and needle not in name.lower():
            return
        tid = str(task.id)
        if (rid, tid) in seen:
            return
        seen.add((rid, tid))
        bucket = rows.setdefault(
            rid,
            {"resource_id": rid, "resource_kind": kind, "resource_name": name,
             "meta": meta, "allocated_tasks": []},
        )
        bucket["allocated_tasks"].append({
            "task_id": tid,
            "key": task.key,
            "title": task.summary,
            "start_date": _start_date(task),
            "end_date": _end_date(task),
            "progress": _progress(task.status),
            "status": str(task.status),
            "allocation": allocation,
        })

    # 1) Explicit assignments (employees + equipment).
    stmt = (
        select(TaskAssignment, Task, User, Equipment, Department)
        .join(Task, Task.id == TaskAssignment.task_id)
        .outerjoin(User, User.id == TaskAssignment.employee_id)
        .outerjoin(Equipment, Equipment.id == TaskAssignment.equipment_id)
        .outerjoin(Department, Department.id == User.department_id)
        .where(Task.is_deleted.is_(False), overlap)
    )
    for asg, task, emp, eq, dept in (await db.execute(stmt)).all():
        if emp is not None and "employee" in kinds:
            if department_id is not None and emp.department_id != department_id:
                continue
            name = f"{emp.first_name} {emp.last_name}".strip() or emp.username
            add(f"emp_{emp.id}", "employee", name, {"department": dept.name if dept else None}, task, asg.allocation)
        elif eq is not None and "equipment" in kinds:
            add(f"eq_{eq.id}", "equipment", eq.name,
                {"inventory_no": eq.inventory_no, "category": eq.category}, task, asg.allocation)

    # 2) Primary assignee fallback — tasks whose assignee has no explicit
    #    assignment row still show up in the employee load (keeps the resource
    #    view consistent with the rest of the app for newly created tasks).
    if "employee" in kinds:
        stmt2 = (
            select(Task, User, Department)
            .join(User, User.id == Task.assignee_id)
            .outerjoin(Department, Department.id == User.department_id)
            .where(Task.is_deleted.is_(False), Task.assignee_id.isnot(None), overlap)
        )
        for task, emp, dept in (await db.execute(stmt2)).all():
            if department_id is not None and emp.department_id != department_id:
                continue
            name = f"{emp.first_name} {emp.last_name}".strip() or emp.username
            add(f"emp_{emp.id}", "employee", name, {"department": dept.name if dept else None}, task, 100)

    # Employees first, then equipment; alphabetical within each group.
    ordered = sorted(
        rows.values(),
        key=lambda r: (r["resource_kind"] != "employee", r["resource_name"].lower()),
    )
    return {"range": {"from": dt_from, "to": dt_to}, "resources": ordered}
