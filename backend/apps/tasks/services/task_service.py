"""Core task business logic.

Ported from ``services/task/app/services/task_service.py`` plus the query
side of ``app/repositories/task_repo.py``. The FastAPI split (service +
repository) collapses here: the ORM is the repository, so keeping a separate
one would be a layer of pass-throughs. Filtering/visibility helpers that
lived in ``TaskRepository`` are the ``_*_q`` builders below.

Jira + SharePoint workflow, unchanged from the original:

* ``Task.assignee_id`` is the *primary* assignee; the source of truth for
  the full crew is ``TaskAssignee``, which carries a role. The two are kept
  in sync here, never by callers.
* ``Task.supervisor_id`` is single; the supervisor grants edit rights to
  delegates.
* Watchers follow a task — visible, notified, no edit rights.
* ``progress_percent`` is independent of status; reaching ``done`` fills it
  to 100 (in ``Task.apply_transition``).
"""

from __future__ import annotations

import logging
from datetime import timedelta

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count, Q
from django.db.models.functions import TruncDate
from django.http import Http404
from django.utils import timezone

from ..models import (
    AssigneeRole,
    Label,
    Notification,
    Status,
    TERMINAL_STATUSES,
    TRANSITIONS,
    Task,
    TaskActivity,
    TaskAssignee,
    TaskDelegate,
    TaskDepartmentLink,
    TaskWatcher,
)
from . import hydration
from .reference_service import resolve_task_type_id
from .sequence_service import due_date_from_working_days, next_task_key

logger = logging.getLogger(__name__)

# Scalar fields whose changes are written to the activity log. Copied from
# the original's ``TRACKED_FIELDS`` — the list is a product decision (what
# the task history shows), not an implementation detail.
TRACKED_FIELDS = [
    "summary", "description", "task_type_id", "priority", "status",
    "assignee_id", "supervisor_id", "project_id", "progress_percent",
    "due_date", "start_date", "estimated_working_days",
]


# ─────────────────────────────────────────────────────────────────────────
# Visibility
# ─────────────────────────────────────────────────────────────────────────

def user_department_id(user_id: int) -> int | None:
    """The caller's HR department.

    The original read it from the local user replica; with the replica gone
    (Р2) it comes from ``apps.hr.interface`` — see
    ``hydration.employee_department_id`` for what ``None`` means.
    """
    return hydration.employee_department_id(user_id)


def _participant_q(user_id: int) -> Q:
    """Tasks where the user has any stake at all."""
    return (
        Q(assignee_id=user_id)
        | Q(reporter_id=user_id)
        | Q(supervisor_id=user_id)
        | Q(assignees__user_id=user_id)
        | Q(delegates__user_id=user_id)
        | Q(watchers__user_id=user_id)
    )


def _employee_visibility_q(user_id: int, department_id: int | None) -> Q:
    q = _participant_q(user_id)
    if department_id is not None:
        # Unclaimed work in your own department is visible so it can be
        # picked up — but only while it is still unassigned and open.
        q |= Q(department_id=department_id, assignee_id__isnull=True,
               status__in=[Status.BACKLOG, Status.TODO])
    return q


def _report_visibility_q(user_id: int, department_id: int | None) -> Q:
    q = Q(Q(assignee_id=user_id) | Q(assignees__user_id=user_id),
          status__in=list(TERMINAL_STATUSES))
    if department_id is not None:
        q |= Q(department_id=department_id, assignee_id__isnull=True,
               status__in=[Status.BACKLOG, Status.TODO])
    return q


def visibility_q(visibility: str, user_id: int | None,
                 department_id: int | None) -> Q | None:
    """``None`` means unrestricted; a false ``Q`` means "nothing visible"."""
    if visibility == "all":
        return None
    if user_id is None:
        return Q(pk__in=[])
    if visibility == "employee":
        return _employee_visibility_q(user_id, department_id)
    if visibility == "reports":
        return _report_visibility_q(user_id, department_id)
    return Q(pk__in=[])


def scope_for(token, *, reports: bool = False) -> tuple[str, int | None]:
    """Visibility mode + department for the caller. Elevated users see all."""
    if token.is_elevated:
        return "all", None
    return ("reports" if reports else "employee"), user_department_id(token.user_id)


# ─────────────────────────────────────────────────────────────────────────
# Queries
# ─────────────────────────────────────────────────────────────────────────

def _base_queryset():
    return Task.objects.filter(is_deleted=False)


def filtered_tasks(*, status=None, priority=None, task_type=None,
                   task_type_id=None, assignee_id=None, reporter_id=None,
                   supervisor_id=None, department_id=None, project_id=None,
                   project_unset=False, parent_id=None, label_id=None,
                   search=None, visibility="all", visibility_user_id=None,
                   visibility_department_id=None):
    qs = _base_queryset()

    vq = visibility_q(visibility, visibility_user_id, visibility_department_id)
    if vq is not None:
        qs = qs.filter(vq)

    if status:
        qs = qs.filter(status=status)
    if priority:
        qs = qs.filter(priority=priority)
    if task_type:
        qs = qs.filter(task_type__slug=task_type)
    if task_type_id is not None:
        qs = qs.filter(task_type_id=task_type_id)
    if assignee_id is not None:
        # Either the denormalised primary FK or the crew table, so
        # "tasks X works on" is right whether X is primary or collaborator.
        qs = qs.filter(Q(assignee_id=assignee_id)
                       | Q(assignees__user_id=assignee_id))
    if reporter_id is not None:
        qs = qs.filter(reporter_id=reporter_id)
    if supervisor_id is not None:
        qs = qs.filter(supervisor_id=supervisor_id)
    if department_id is not None:
        qs = qs.filter(department_id=department_id)
    if project_id is not None:
        qs = qs.filter(project_id=project_id)
    if project_unset:
        qs = qs.filter(project_id__isnull=True)
    if parent_id is not None:
        qs = qs.filter(parent_id=parent_id)
    if label_id is not None:
        qs = qs.filter(labels__id=label_id)
    if search:
        qs = qs.filter(Q(summary__icontains=search)
                       | Q(description__icontains=search)
                       | Q(key__icontains=search))

    # The visibility and assignee filters join across to-many tables
    # (assignees/delegates/watchers/labels), which multiplies rows. Without
    # distinct() a task the user reaches through two roles would appear
    # twice in the list — the original avoided it with EXISTS subqueries.
    return qs.distinct()


def list_tasks(*, offset: int = 0, limit: int = 50, **filters) -> list[Task]:
    qs = (filtered_tasks(**filters)
          .select_related("task_type", "project", "parent")
          .prefetch_related("labels", "assignees", "department_links",
                            "subtasks")
          .order_by("-created_at"))
    return list(qs[offset:offset + limit])


def get_task(task_id: int, *, visibility="all", visibility_user_id=None,
             visibility_department_id=None) -> Task:
    """Load one task honouring visibility. Raises 404 when out of scope —
    deliberately indistinguishable from "does not exist", so the endpoint
    does not leak the existence of tasks the caller may not see."""
    qs = filtered_tasks(visibility=visibility,
                        visibility_user_id=visibility_user_id,
                        visibility_department_id=visibility_department_id)
    task = (qs.select_related("task_type", "project", "parent")
            # Both ends of both link directions: the response reports
            # source/target absolutely, so an outgoing link still needs its
            # source (this task) resolved as an object.
            .prefetch_related("labels", "assignees", "delegates", "watchers",
                              "comments", "attachments", "activities",
                              "outgoing_links__source", "outgoing_links__target",
                              "incoming_links__source", "incoming_links__target",
                              "department_links", "subtasks")
            .filter(pk=task_id).first())
    if task is None:
        raise Http404("Task not found")
    return task


def load_for_action(task_id: int, token) -> Task:
    """Visibility-checked load used by every mutating endpoint.

    Does NOT check write permission — the caller decides whether full edit,
    soft edit, or mere visibility is required.
    """
    visibility, department_id = scope_for(token)
    return get_task(task_id, visibility=visibility,
                    visibility_user_id=token.user_id,
                    visibility_department_id=department_id)


# ─────────────────────────────────────────────────────────────────────────
# Permissions
# ─────────────────────────────────────────────────────────────────────────

def can_edit(task: Task, user_id: int, is_elevated: bool) -> bool:
    """Full edit — any field. Elevated / reporter / supervisor / delegate."""
    if is_elevated:
        return True
    if task.reporter_id == user_id or task.supervisor_id == user_id:
        return True
    return task.delegates.filter(user_id=user_id).exists()


def can_progress(task: Task, user_id: int, is_elevated: bool) -> bool:
    """Soft edit — status / progress / comments. Adds any assignee."""
    if can_edit(task, user_id, is_elevated):
        return True
    if task.assignee_id == user_id:
        return True
    return task.assignees.filter(user_id=user_id).exists()


def require_full_edit(task: Task, token) -> None:
    if not can_edit(task, token.user_id, token.is_elevated):
        raise PermissionDenied(
            "Only supervisor, delegate, reporter or admin can edit this task"
        )


def require_soft_edit(task: Task, token) -> None:
    if not can_progress(task, token.user_id, token.is_elevated):
        raise PermissionDenied(
            "Only assignees, supervisor, delegate, reporter or admin can "
            "change status/progress"
        )


# ─────────────────────────────────────────────────────────────────────────
# Mutations
# ─────────────────────────────────────────────────────────────────────────

def _compose_initial_crew(primary_id: int | None,
                          explicit: list) -> list[tuple[int, str]]:
    """Merge the legacy single ``assignee_id`` with the explicit crew list.

    Rules kept from the original: an explicit primary beats the legacy one,
    and the legacy id counts as primary only when it has no explicit row of
    its own. Returns ``(user_id, role)`` pairs.
    """
    by_user: dict[int, str] = {a.user_id: a.role for a in explicit}
    if primary_id is not None and primary_id not in by_user:
        by_user[primary_id] = AssigneeRole.PRIMARY

    primaries = [uid for uid, role in by_user.items()
                 if role == AssigneeRole.PRIMARY]
    if len(primaries) > 1:
        explicit_primary = {a.user_id for a in explicit
                            if a.role == AssigneeRole.PRIMARY}
        for uid in list(by_user):
            if by_user[uid] == AssigneeRole.PRIMARY and uid not in explicit_primary:
                by_user[uid] = AssigneeRole.COLLABORATOR
    return list(by_user.items())


def _notify(recipient_id: int, actor_id: int | None, task: Task,
            verb: str) -> None:
    """Best-effort notification. The original swallowed every failure here
    so a notification problem could never fail the mutation that caused it —
    kept, but logged rather than silently passed."""
    try:
        Notification.objects.create(recipient_id=recipient_id,
                                    actor_id=actor_id, task=task, verb=verb,
                                    target_type="task", target_id=task.id)
    except Exception:
        logger.exception("tasks: failed to write notification %r", verb)


def _log(task: Task, actor_id: int | None, field_name: str,
         old_value, new_value) -> None:
    TaskActivity.objects.create(
        task=task, actor_id=actor_id, field_name=field_name,
        old_value=str(old_value) if old_value is not None else None,
        new_value=str(new_value) if new_value is not None else None,
    )


@transaction.atomic
def create_task(data, user_id: int | None = None) -> Task:
    due_date = data.due_date
    if data.estimated_working_days and data.start_date:
        # A computed deadline wins over a client-sent one, as in the original.
        computed = due_date_from_working_days(data.start_date,
                                              data.estimated_working_days)
        if computed is not None:
            due_date = computed

    crew = _compose_initial_crew(data.assignee_id, data.assignees)
    primary_id = next((uid for uid, role in crew
                       if role == AssigneeRole.PRIMARY), None)

    dept_ids = list(dict.fromkeys(
        ([data.department_id] if data.department_id else [])
        + list(data.department_ids)
    ))
    primary_dept = data.department_id or (dept_ids[0] if dept_ids else None)

    task = Task.objects.create(
        key=next_task_key(),
        summary=data.summary,
        description=data.description,
        task_type_id=resolve_task_type_id(data.task_type_id, data.task_type),
        priority=data.priority,
        status=data.status,
        reporter_id=data.reporter_id or user_id,
        assignee_id=primary_id,
        supervisor_id=data.supervisor_id,
        department_id=primary_dept,
        project_id=data.project_id,
        parent_id=data.parent_id,
        progress_percent=data.progress_percent,
        due_date=due_date,
        start_date=data.start_date,
        estimated_working_days=data.estimated_working_days,
    )

    # Department ids are hr-owned and unvalidated here. The original filtered
    # them against its local replica to avoid violating a FK; with the
    # replica gone there is no FK to violate, and filtering through
    # hr.interface would make task creation fail whenever hr is disabled.
    # Unknown ids are stored and simply do not hydrate to a name.
    if dept_ids:
        TaskDepartmentLink.objects.bulk_create(
            [TaskDepartmentLink(task=task, department_id=d) for d in dept_ids]
        )

    if data.label_ids:
        # Labels are local, so unknown ids are a client error we can detect —
        # keep only real ones, exactly as the original did.
        task.labels.set(Label.objects.filter(id__in=data.label_ids))

    TaskAssignee.objects.bulk_create(
        [TaskAssignee(task=task, user_id=uid, role=role) for uid, role in crew]
    )

    for uid, _role in crew:
        _notify(uid, user_id, task, f"task_assigned:{task.key}")

    return task


@transaction.atomic
def update_task(task_id: int, data, user_id: int | None = None) -> Task:
    task = Task.objects.filter(pk=task_id, is_deleted=False).first()
    if task is None:
        raise Http404("Task not found")

    changes = data.model_dump(exclude_unset=True)
    label_ids = changes.pop("label_ids", None)
    department_ids = changes.pop("department_ids", None)

    slug = changes.pop("task_type", None)
    if slug is not None and "task_type_id" not in changes:
        changes["task_type_id"] = resolve_task_type_id(None, slug)

    # Setting the multi-department set also realigns the primary, unless the
    # caller set it explicitly in the same request.
    if department_ids is not None and "department_id" not in changes:
        changes["department_id"] = department_ids[0] if department_ids else None

    if "status" in changes:
        target = changes.pop("status")
        try:
            task.apply_transition(target)
        except ValueError as exc:
            # Invalid FSM edge -> the original's 400.
            raise ValueError(str(exc)) from exc
        if task.assignee_id:
            _notify(task.assignee_id, user_id, task,
                    f"status_changed:{task.key}")

    for field_name in TRACKED_FIELDS:
        if field_name in changes:
            old = getattr(task, field_name)
            new = changes[field_name]
            if old != new:
                _log(task, user_id, field_name, old, new)

    for field, value in changes.items():
        setattr(task, field, value)
    task.save()

    if "assignee_id" in changes:
        _sync_primary_assignee(task, changes["assignee_id"])
        if changes["assignee_id"]:
            _notify(changes["assignee_id"], user_id, task,
                    f"task_assigned:{task.key}")

    if label_ids is not None:
        task.labels.set(Label.objects.filter(id__in=label_ids))

    if department_ids is not None:
        task.department_links.all().delete()
        TaskDepartmentLink.objects.bulk_create(
            [TaskDepartmentLink(task=task, department_id=d)
             for d in dict.fromkeys(department_ids)]
        )

    return task


def _sync_primary_assignee(task: Task, new_primary_id: int | None) -> None:
    """Keep ``TaskAssignee`` consistent after the legacy scalar changed."""
    task.assignees.filter(role=AssigneeRole.PRIMARY).exclude(
        user_id=new_primary_id
    ).update(role=AssigneeRole.COLLABORATOR)
    if new_primary_id is None:
        return
    row = task.assignees.filter(user_id=new_primary_id).first()
    if row is not None:
        row.role = AssigneeRole.PRIMARY
        row.save(update_fields=["role"])
    else:
        TaskAssignee.objects.create(task=task, user_id=new_primary_id,
                                    role=AssigneeRole.PRIMARY)


def delete_task(task_id: int) -> None:
    """Soft delete — the row stays for history and the ETL."""
    updated = Task.objects.filter(pk=task_id, is_deleted=False).update(
        is_deleted=True, updated_at=timezone.now()
    )
    if not updated:
        raise Http404("Task not found")


def available_transitions(task_id: int) -> list[str]:
    task = Task.objects.filter(pk=task_id, is_deleted=False).first()
    if task is None:
        raise Http404("Task not found")
    return list(TRANSITIONS.get(task.status, frozenset()))


# ── participants ────────────────────────────────────────────────────────

@transaction.atomic
def replace_assignees(task_id: int, assignments: list,
                      actor_id: int | None) -> Task:
    """Atomically replace the crew — anyone not in the list is removed."""
    task = Task.objects.filter(pk=task_id, is_deleted=False).first()
    if task is None:
        raise Http404("Task not found")

    existing = {row.user_id: row for row in task.assignees.all()}
    new_ids = {a.user_id for a in assignments}

    task.assignees.exclude(user_id__in=new_ids).delete()

    for a in assignments:
        row = existing.get(a.user_id)
        if row is not None:
            if row.role != a.role:
                row.role = a.role
                row.save(update_fields=["role"])
        else:
            TaskAssignee.objects.create(task=task, user_id=a.user_id,
                                        role=a.role)
            _notify(a.user_id, actor_id, task, f"task_assigned:{task.key}")

    primary = next((a.user_id for a in assignments
                    if a.role == AssigneeRole.PRIMARY), None)
    if task.assignee_id != primary:
        _log(task, actor_id, "assignee_id", task.assignee_id, primary)
        task.assignee_id = primary
        task.save(update_fields=["assignee_id", "updated_at"])
    return task


@transaction.atomic
def set_supervisor(task_id: int, supervisor_id: int | None,
                   actor_id: int | None) -> Task:
    task = Task.objects.filter(pk=task_id, is_deleted=False).first()
    if task is None:
        raise Http404("Task not found")
    if task.supervisor_id == supervisor_id:
        return task

    _log(task, actor_id, "supervisor_id", task.supervisor_id, supervisor_id)
    task.supervisor_id = supervisor_id
    task.save(update_fields=["supervisor_id", "updated_at"])
    if supervisor_id:
        _notify(supervisor_id, actor_id, task, f"task_supervisor_set:{task.key}")
    return task


@transaction.atomic
def add_delegate(task_id: int, user_id: int, granted_by: int | None) -> Task:
    task = Task.objects.filter(pk=task_id, is_deleted=False).first()
    if task is None:
        raise Http404("Task not found")
    if task.delegates.filter(user_id=user_id).exists():
        return task  # idempotent

    TaskDelegate.objects.create(task=task, user_id=user_id,
                                granted_by_id=granted_by)
    _log(task, granted_by, "delegates", None, f"+{user_id}")
    _notify(user_id, granted_by, task, f"task_delegated:{task.key}")
    return task


@transaction.atomic
def remove_delegate(task_id: int, user_id: int, actor_id: int | None) -> Task:
    task = Task.objects.filter(pk=task_id, is_deleted=False).first()
    if task is None:
        raise Http404("Task not found")
    deleted, _ = task.delegates.filter(user_id=user_id).delete()
    if deleted:
        _log(task, actor_id, "delegates", user_id, None)
    return task


def add_watcher(task_id: int, user_id: int) -> Task:
    task = Task.objects.filter(pk=task_id, is_deleted=False).first()
    if task is None:
        raise Http404("Task not found")
    TaskWatcher.objects.get_or_create(task=task, user_id=user_id)
    return task


def remove_watcher(task_id: int, user_id: int) -> Task:
    task = Task.objects.filter(pk=task_id, is_deleted=False).first()
    if task is None:
        raise Http404("Task not found")
    task.watchers.filter(user_id=user_id).delete()
    return task


@transaction.atomic
def set_progress(task_id: int, percent: int, actor_id: int | None) -> Task:
    task = Task.objects.filter(pk=task_id, is_deleted=False).first()
    if task is None:
        raise Http404("Task not found")
    percent = max(0, min(100, int(percent)))
    if task.progress_percent == percent:
        return task
    _log(task, actor_id, "progress_percent", task.progress_percent, percent)
    task.progress_percent = percent
    task.save(update_fields=["progress_percent", "updated_at"])
    return task


# ─────────────────────────────────────────────────────────────────────────
# Statistics
# ─────────────────────────────────────────────────────────────────────────

def task_stats(*, department_id=None, project_id=None, visibility="all",
               visibility_user_id=None, visibility_department_id=None) -> dict:
    qs = filtered_tasks(department_id=department_id, project_id=project_id,
                        visibility=visibility,
                        visibility_user_id=visibility_user_id,
                        visibility_department_id=visibility_department_id)

    total = qs.count()

    # Every aggregate below counts DISTINCT ids on purpose. ``filtered_tasks``
    # joins across to-many tables (assignees/delegates/watchers/labels) for
    # the visibility rules, which multiplies rows per task; ``.distinct()``
    # dedupes the *rows* a list endpoint returns but does NOT dedupe inside a
    # GROUP BY, so a plain Count("id") would report a task once per role the
    # caller holds on it.
    n = Count("id", distinct=True)

    by_status = {row["status"]: row["n"] for row in
                 qs.values("status").annotate(n=n)}
    by_priority = {row["priority"]: row["n"] for row in
                   qs.values("priority").annotate(n=n)}
    # NULL task_type buckets under the literal 'unknown' so the response
    # stays dict[str, int], as the original declared.
    by_type = {(row["task_type__slug"] or "unknown"): row["n"] for row in
               qs.values("task_type__slug").annotate(n=n)}

    since = timezone.now().date() - timedelta(days=30)
    created_per_day = [
        {"day": str(row["day"]), "count": row["n"]}
        for row in (qs.filter(created_at__date__gte=since)
                    .values(day=TruncDate("created_at"))
                    .annotate(n=n).order_by("day"))
    ]
    resolved_per_day = [
        {"day": str(row["day"]), "count": row["n"]}
        for row in (qs.filter(completed_at__isnull=False,
                              completed_at__date__gte=since)
                    .values(day=TruncDate("completed_at"))
                    .annotate(n=n).order_by("day"))
    ]

    dept_rows = list(qs.values("department_id").annotate(n=n).order_by("-n"))
    dept_names = hydration.department_briefs(
        [row["department_id"] for row in dept_rows]
    )
    by_department = [
        {
            "department__id": row["department_id"],
            "department__name": hydration.department_name(
                dept_names, row["department_id"]) or "Без отдела",
            "count": row["n"],
        }
        for row in dept_rows
    ]

    assignee_rows = list(qs.filter(assignee_id__isnull=False)
                         .values("assignee_id").annotate(n=n).order_by("-n"))
    user_briefs = hydration.user_briefs(
        [row["assignee_id"] for row in assignee_rows]
    )
    by_assignee = []
    for row in assignee_rows:
        brief = user_briefs.get(row["assignee_id"], {})
        # The original exposed first/last name separately, straight off the
        # replica columns. The users brief only offers a composed
        # ``full_name``, so it is split back on the first space — the
        # frontend joins these two fields for display anyway.
        full = brief.get("full_name") or ""
        first, _, last = full.partition(" ")
        by_assignee.append({
            "assignee__id": row["assignee_id"],
            "assignee__first_name": first,
            "assignee__last_name": last,
            "assignee__username": brief.get("username") or "",
            "count": row["n"],
        })

    return {
        "total": total,
        "by_status": by_status,
        "by_priority": by_priority,
        "by_type": by_type,
        "by_department": by_department,
        "by_assignee": by_assignee,
        "created_per_day": created_per_day,
        "resolved_per_day": resolved_per_day,
    }
