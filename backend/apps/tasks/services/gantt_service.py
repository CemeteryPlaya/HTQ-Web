"""Aggregation for the two Gantt views.

* ``reports_gantt``  — flat list of selected tasks (planned/actual dates).
* ``resource_gantt`` — tasks grouped by resource row (employees + equipment).

Ported from ``services/task/app/services/gantt_service.py``. The original
joined the ``task_users``/``task_departments`` replicas to get employee
names and their department; with the replicas gone (Р2) names come from
``apps.users.interface`` in one batch.

One honest wart, called out rather than hidden: the ``department_id`` filter
on the resource Gantt needs *employee → department*, and the agreed
interface (PLAN.md §7) exposes only ``get_employee_brief(user_id)`` — a
single-id call, with no bulk form. So that filter, and only that filter,
resolves per employee (memoised within the request, and only when the caller
actually passes ``department_id``). It is bounded by the number of distinct
employees with work in the window, not by tasks. A bulk
``get_employees_brief(ids)`` would remove it; that is an A↔B contract change,
not something this side may make unilaterally (§1.5 п.3).
"""

from __future__ import annotations

from datetime import date

from django.db.models import F, Q
from django.db.models.functions import Coalesce

from ..models import Status, Task, TaskAssignment
from . import hydration

# Terminal statuses stamp ``completed_at`` — the bar ends there.
_DONE = (Status.DONE, Status.CANCELLED)

# Coarse progress per status (there is no time-tracking) — good enough for
# the visual, and copied value-for-value so bars do not shift after the port.
_PROGRESS = {
    Status.BACKLOG: 0.0,
    Status.TODO: 0.0,
    Status.IN_PROGRESS: 0.4,
    Status.BLOCKED: 0.4,
    Status.IN_REVIEW: 0.75,
    Status.DONE: 1.0,
    Status.CANCELLED: 1.0,
}


def _progress(status: str) -> float:
    return _PROGRESS.get(status, 0.0)


def _end_date(task: Task) -> date | None:
    """Bar end: actual completion for closed tasks, else the planned due date."""
    if task.status in _DONE and task.completed_at:
        return task.completed_at.date()
    return task.due_date or (task.completed_at.date() if task.completed_at
                             else None)


def _start_date(task: Task) -> date | None:
    return task.start_date or task.due_date


def reports_gantt(ids: list[int] | None,
                  statuses: list[str] | None) -> dict:
    qs = Task.objects.filter(is_deleted=False)
    if ids:
        qs = qs.filter(id__in=ids)
    if statuses:
        qs = qs.filter(status__in=statuses)
    tasks = list(qs.order_by(F("start_date").asc(nulls_last=True), "id"))
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
                # Always empty in the original too — the field exists for the
                # chart's schema, never populated.
                "assignees": [],
            }
            for t in tasks
        ]
    }


class _DepartmentResolver:
    """employee id -> department id, memoised, hr-interface backed.

    Only instantiated when the caller passes a ``department_id`` filter (see
    the module docstring). When hr cannot answer, ``resolve`` returns
    ``None``, which the filter treats as "does not match" — a disabled hr
    narrows the report rather than silently ignoring the filter.
    """

    def __init__(self):
        self._cache: dict[int, int | None] = {}

    def resolve(self, employee_id: int) -> int | None:
        if employee_id not in self._cache:
            self._cache[employee_id] = hydration.employee_department_id(
                employee_id)
        return self._cache[employee_id]


def resource_gantt(dt_from: date, dt_to: date, kinds: set[str],
                   department_id: int | None = None,
                   search: str | None = None) -> dict:
    # The original's overlap test, expressed in SQL exactly as it was:
    # a one-dated task is treated as a zero-length bar on that date, and a
    # task with no dates at all has no bar and never appears.
    tasks_in_window = (
        Task.objects.filter(is_deleted=False)
        .filter(Q(start_date__isnull=False) | Q(due_date__isnull=False))
        .annotate(eff_start=Coalesce("start_date", "due_date"),
                  eff_end=Coalesce("due_date", "start_date"))
        .filter(eff_start__lte=dt_to, eff_end__gte=dt_from)
    )

    rows: dict[str, dict] = {}
    seen: set[tuple[str, str]] = set()
    needle = (search or "").strip().lower()
    departments = _DepartmentResolver() if department_id is not None else None

    def add(rid: str, kind: str, name: str, meta: dict, task: Task,
            allocation: int) -> None:
        if needle and needle not in name.lower():
            return
        tid = str(task.id)
        if (rid, tid) in seen:
            return
        seen.add((rid, tid))
        bucket = rows.setdefault(rid, {
            "resource_id": rid, "resource_kind": kind, "resource_name": name,
            "meta": meta, "allocated_tasks": [],
        })
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

    # 1) Explicit resource assignments (employees + equipment).
    assignments = list(TaskAssignment.objects
                       .filter(task__in=tasks_in_window)
                       .select_related("task", "equipment"))
    # 2) Primary-assignee fallback: a task whose assignee has no explicit
    #    assignment row still shows in the employee load, so newly created
    #    tasks are not invisible on the resource view.
    fallback = ([t for t in tasks_in_window.filter(assignee_id__isnull=False)]
                if "employee" in kinds else [])

    employee_ids = {a.employee_id for a in assignments if a.employee_id}
    employee_ids |= {t.assignee_id for t in fallback}
    users = hydration.user_briefs(employee_ids)

    def employee_name(employee_id: int) -> str:
        # Falls back to a stable placeholder rather than an empty row when
        # users cannot resolve the id — an unnamed bar is still useful load.
        return (hydration.user_name(users, employee_id)
                or f"user:{employee_id}")

    def department_allows(employee_id: int) -> bool:
        if departments is None:
            return True
        return departments.resolve(employee_id) == department_id

    # ``meta.department`` stays None for employee rows. The original read it
    # off the joined replica; filling it now would need a bulk
    # employee -> department call, which the §7 contract does not offer (see
    # the module docstring). The key is kept so the payload shape is
    # unchanged for the chart.
    for assignment in assignments:
        task = assignment.task
        if assignment.employee_id and "employee" in kinds:
            if not department_allows(assignment.employee_id):
                continue
            add(f"emp_{assignment.employee_id}", "employee",
                employee_name(assignment.employee_id),
                {"department": None}, task, assignment.allocation)
        elif assignment.equipment_id and "equipment" in kinds:
            equipment = assignment.equipment
            add(f"eq_{assignment.equipment_id}", "equipment", equipment.name,
                {"inventory_no": equipment.inventory_no,
                 "category": equipment.category},
                task, assignment.allocation)

    for task in fallback:
        if not department_allows(task.assignee_id):
            continue
        add(f"emp_{task.assignee_id}", "employee",
            employee_name(task.assignee_id), {"department": None}, task, 100)

    # Employees first, then equipment; alphabetical within each group.
    ordered = sorted(rows.values(),
                     key=lambda r: (r["resource_kind"] != "employee",
                                    r["resource_name"].lower()))
    return {"range": {"from": dt_from, "to": dt_to}, "resources": ordered}
