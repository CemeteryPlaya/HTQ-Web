"""Task domain models — idiomatic Django, built from scratch in ``public``.

Ported from the ``services/task`` FastAPI microservice (SQLAlchemy +
alembic). Per PLAN.md §3 this repo is a standalone copy that never runs
side-by-side with the FastAPI stack, so alembic parity is explicitly NOT a
goal: table/constraint/index names are Django-generated, PG enums become
``TextChoices``, and the schema is built by a natural ``makemigrations``.

Two tables from the original are deliberately **absent** (decision Р2,
PLAN.md §6.1): ``task_users`` and ``task_departments`` were denormalised
replicas kept in sync over Redis pub/sub from user-service and hr-service.
In the Django monolith there is nothing to replicate — apps talk through
``interface.py``. Every column that was a FK into one of those two replica
tables is therefore a plain, FK-less integer id here:

* ``reporter_id`` / ``assignee_id`` / ``supervisor_id`` / ``owner_id`` /
  ``actor_id`` / ``recipient_id`` / ``user_id`` / ``employee_id``
  — resolved through ``apps.users.interface.get_users_brief``;
* ``department_id`` — resolved through ``apps.hr.interface``.

Consequences worth knowing, because the original leaned on those FKs:

* ``ON DELETE CASCADE`` from the replica tables is gone. Nothing cascades
  from a deleted user; rows keep the orphaned id and display-name hydration
  simply yields ``None`` for it — the same result the original produced when
  the replica lagged, so the API shape is unchanged.
* The denormalised ``*_name`` / ``avatar_url`` attributes the SQLAlchemy
  models exposed as ``@property`` off a loaded relationship do not exist on
  these models. They are response-shape concerns and are computed in the
  service layer, which batches the ``interface`` lookups — a model-level
  property would have meant an N+1 across an app boundary.

``db_default=`` is set on every column carrying a concrete scalar default so
a direct INSERT that bypasses the ORM still lands sane values, and
``db_index=True`` mirrors every ``index=True`` in the SQLAlchemy source (FK
columns are indexed by Django automatically and get no redundant flag) —
PLAN.md §3's "не терять индексы" rule.
"""

from django.db import models
from django.db.models.functions import Now
from django.utils import timezone


# ─────────────────────────────────────────────────────────────────────────
# Enumerations (PG ENUM in the original → TextChoices here)
# ─────────────────────────────────────────────────────────────────────────

class Status(models.TextChoices):
    BACKLOG = "backlog"
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    IN_REVIEW = "in_review"
    BLOCKED = "blocked"
    DONE = "done"
    CANCELLED = "cancelled"


class Priority(models.TextChoices):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    TRIVIAL = "trivial"


class ProjectStatus(models.TextChoices):
    ACTIVE = "active"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class LinkType(models.TextChoices):
    BLOCKS = "blocks"
    IS_BLOCKED_BY = "is_blocked_by"
    RELATES_TO = "relates_to"
    DUPLICATES = "duplicates"


class AssigneeRole(models.TextChoices):
    PRIMARY = "primary"
    COLLABORATOR = "collaborator"


# Terminal statuses — entering one stamps ``completed_at``.
TERMINAL_STATUSES = frozenset({Status.DONE, Status.CANCELLED})

# FSM transitions: from_state -> allowed target states. Copied verbatim from
# services/task/app/models/task.py. Deliberately permissive: workflow tasks
# routinely bounce between states (unblock then re-cancel) and a strict graph
# causes user friction.
TRANSITIONS: dict[str, frozenset[str]] = {
    Status.BACKLOG: frozenset({Status.TODO, Status.IN_PROGRESS, Status.CANCELLED}),
    Status.TODO: frozenset({Status.IN_PROGRESS, Status.BLOCKED, Status.BACKLOG,
                            Status.CANCELLED}),
    Status.IN_PROGRESS: frozenset({Status.IN_REVIEW, Status.BLOCKED, Status.DONE,
                                   Status.TODO, Status.CANCELLED}),
    Status.IN_REVIEW: frozenset({Status.DONE, Status.IN_PROGRESS, Status.BLOCKED,
                                 Status.CANCELLED}),
    Status.BLOCKED: frozenset({Status.IN_PROGRESS, Status.TODO, Status.CANCELLED}),
    Status.DONE: frozenset({Status.IN_PROGRESS, Status.CANCELLED}),   # reopen
    Status.CANCELLED: frozenset({Status.BACKLOG, Status.TODO}),       # restore
}


# ─────────────────────────────────────────────────────────────────────────
# Reference data
# ─────────────────────────────────────────────────────────────────────────

class TaskType(models.Model):
    """A user-configurable task type — DB-backed replacement for the legacy
    PG enum (``task``/``bug``/``story``/``epic``/``subtask``).

    Different business domains have wildly different vocabularies for "what
    kind of work is this": dev teams talk about bug/story/epic, ops wants
    maintenance/incident, HR wants onboarding/offboarding. The five original
    enum values are seeded as ``is_system`` rows and are protected from
    deletion through the API so historical data keeps resolving.
    """

    slug = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=100)
    color = models.CharField(max_length=20, default="#6b7280", db_default="#6b7280")
    icon = models.CharField(max_length=50, null=True, blank=True)
    is_system = models.BooleanField(default=False, db_default=False)

    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())
    updated_at = models.DateTimeField(auto_now=True, db_default=Now())

    def __repr__(self) -> str:  # pragma: no cover
        return f"<TaskType id={self.id} slug={self.slug!r}>"


class Label(models.Model):
    """Label/tag for task categorisation."""

    name = models.CharField(max_length=100, unique=True)
    color = models.CharField(max_length=7, default="#808080", db_default="#808080")

    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())
    updated_at = models.DateTimeField(auto_now=True, db_default=Now())

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Label id={self.id} name={self.name!r}>"


class Equipment(models.Model):
    """Physical resource (machinery/vehicle) the task domain owns outright.

    Unlike the former user/department replicas this is a first-class entity —
    there is no equipment service to replicate from. Used by the resource
    Gantt to group tasks by machine.
    """

    name = models.CharField(max_length=200)
    inventory_no = models.CharField(max_length=50, null=True, blank=True)
    category = models.CharField(max_length=100, null=True, blank=True)
    is_active = models.BooleanField(default=True, db_default=True, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())
    updated_at = models.DateTimeField(auto_now=True, db_default=Now())

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Equipment id={self.id} name={self.name!r}>"


class Project(models.Model):
    """Roadmap-level project grouping tasks.

    Projects are durable business initiatives ("Onboarding revamp") rather
    than software releases — there is no version/release_date semantics.
    A task with ``project=None`` is a standalone work item, a first-class
    state the UI renders differently.

    ``task_count`` / ``done_count`` / ``progress`` were ``ClassVar``
    scratch-space on the SQLAlchemy model, filled by the repository. They are
    not model state and live in the response builder here instead.
    """

    name = models.CharField(max_length=200, unique=True)
    description = models.TextField(default="", blank=True, db_default="")
    status = models.CharField(
        max_length=20, choices=ProjectStatus.choices,
        default=ProjectStatus.ACTIVE, db_default=ProjectStatus.ACTIVE,
    )
    color = models.CharField(max_length=20, default="#3b82f6", db_default="#3b82f6")
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)

    # Р2: FK-less — users/hr own these rows, resolved via their interface.
    owner_id = models.IntegerField(null=True, blank=True, db_index=True)
    department_id = models.IntegerField(null=True, blank=True, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())
    updated_at = models.DateTimeField(auto_now=True, db_default=Now())

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Project id={self.id} name={self.name!r}>"


# ─────────────────────────────────────────────────────────────────────────
# Core entity
# ─────────────────────────────────────────────────────────────────────────

class Task(models.Model):
    """Main task entity with lifecycle management.

    The model intentionally blends Jira and SharePoint semantics:

    * Jira side — ``key``, task type, FSM ``status``, links (blocks /
      relates_to / duplicates), labels, activity log, hierarchy via
      ``parent``.
    * SharePoint side — ``supervisor_id`` (task owner who can delegate),
      delegates (deputies who edit on the supervisor's behalf), watchers
      (followers), ``progress_percent``, multi-assignee with primary +
      collaborator roles.
    """

    key = models.CharField(max_length=20, unique=True, db_index=True)
    summary = models.CharField(max_length=500)
    description = models.TextField(default="", blank=True, db_default="")

    # Classification. SET_NULL so deleting a custom type never cascades into
    # task rows; the response layer falls back to the "task" slug.
    task_type = models.ForeignKey(
        TaskType, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="tasks",
    )
    priority = models.CharField(
        max_length=20, choices=Priority.choices,
        default=Priority.MEDIUM, db_default=Priority.MEDIUM,
    )
    status = models.CharField(
        max_length=20, choices=Status.choices,
        default=Status.TODO, db_default=Status.TODO, db_index=True,
    )

    # SharePoint-style progress. Independent of status — a task can be 70 %
    # done while still in_review, and 100 % does not auto-Done it.
    progress_percent = models.SmallIntegerField(default=0, db_default=0)

    # Р2: FK-less participant ids (see module docstring).
    reporter_id = models.IntegerField(null=True, blank=True, db_index=True)
    # Denormalised pointer to the **primary** assignee for fast filters and
    # Kanban-card display. Source of truth for the full crew is TaskAssignee.
    assignee_id = models.IntegerField(null=True, blank=True, db_index=True)
    supervisor_id = models.IntegerField(null=True, blank=True, db_index=True)
    # Primary department; the full cross-functional set is TaskDepartmentLink.
    department_id = models.IntegerField(null=True, blank=True, db_index=True)

    project = models.ForeignKey(
        Project, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="tasks",
    )
    parent = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="subtasks",
    )

    due_date = models.DateField(null=True, blank=True)
    start_date = models.DateField(null=True, blank=True)
    estimated_working_days = models.IntegerField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    is_deleted = models.BooleanField(default=False, db_default=False, db_index=True)

    labels = models.ManyToManyField(Label, related_name="tasks", blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())
    updated_at = models.DateTimeField(auto_now=True, db_default=Now())

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(start_date__isnull=True)
                | models.Q(due_date__isnull=True)
                | models.Q(start_date__lte=models.F("due_date")),
                name="ck_task_dates",
            ),
        ]

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Task id={self.id} key={self.key!r} status={self.status}>"

    # ── FSM ──────────────────────────────────────────────────────────────
    def can_transition_to(self, target: str) -> bool:
        """Whether ``target`` is reachable from the current status."""
        return target in TRANSITIONS.get(self.status, frozenset())

    def apply_transition(self, target: str) -> None:
        """Apply a status transition, validating it against ``TRANSITIONS``.

        Mirrors the FastAPI original including its side effects: entering a
        terminal status stamps ``completed_at`` (only if unset), leaving one
        clears it so analytics stay honest, and reaching ``done`` forces
        progress to 100 %.
        """
        if not self.can_transition_to(target):
            raise ValueError(
                f"Cannot transition from {self.status} to {target}. "
                f"Allowed: {set(TRANSITIONS.get(self.status, frozenset()))}"
            )
        self.status = target
        if target in TERMINAL_STATUSES:
            if not self.completed_at:
                self.completed_at = timezone.now()
        else:
            # Re-opened — drop the completion stamp.
            self.completed_at = None
        if target == Status.DONE:
            self.progress_percent = 100


class TaskDepartmentLink(models.Model):
    """A task may span several departments (cross-functional work).

    ``Task.department_id`` stays the primary department; this junction holds
    the full set. The original was a bare M2M table into the
    ``task_departments`` replica — with that replica gone (Р2) the far side
    is a plain hr-owned id, so this must be an explicit model rather than a
    Django ``ManyToManyField``.
    """

    task = models.ForeignKey(Task, on_delete=models.CASCADE,
                             related_name="department_links")
    department_id = models.IntegerField(db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["task", "department_id"],
                                    name="uq_task_department_link"),
        ]


# ─────────────────────────────────────────────────────────────────────────
# Participants — multi-assignee, delegates, watchers
# ─────────────────────────────────────────────────────────────────────────

class TaskAssignee(models.Model):
    """One worker on a task, with a role.

    The ``primary`` row is mirrored into ``Task.assignee_id`` for fast
    filter/joins and Kanban-card avatars.
    """

    task = models.ForeignKey(Task, on_delete=models.CASCADE,
                             related_name="assignees")
    user_id = models.IntegerField(db_index=True)
    role = models.CharField(
        max_length=20, choices=AssigneeRole.choices,
        default=AssigneeRole.COLLABORATOR, db_default=AssigneeRole.COLLABORATOR,
    )
    assigned_at = models.DateTimeField(auto_now_add=True, db_default=Now())

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["task", "user_id"],
                                    name="uq_task_assignee"),
        ]


class TaskDelegate(models.Model):
    """Supervisor's deputy on a task — may edit as if they were the supervisor.

    ``granted_by_id`` is who created the delegation (almost always the
    supervisor, but an elevated admin can also push one), kept so the
    activity log can attribute a change to a delegate vs. the supervisor.
    """

    task = models.ForeignKey(Task, on_delete=models.CASCADE,
                             related_name="delegates")
    user_id = models.IntegerField(db_index=True)
    granted_by_id = models.IntegerField(null=True, blank=True)
    granted_at = models.DateTimeField(auto_now_add=True, db_default=Now())

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["task", "user_id"],
                                    name="uq_task_delegate"),
        ]


class TaskWatcher(models.Model):
    """Follower — no edit rights, but sees the task in lists and is notified."""

    task = models.ForeignKey(Task, on_delete=models.CASCADE,
                             related_name="watchers")
    user_id = models.IntegerField(db_index=True)
    subscribed_at = models.DateTimeField(auto_now_add=True, db_default=Now())

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["task", "user_id"],
                                    name="uq_task_watcher"),
        ]


# ─────────────────────────────────────────────────────────────────────────
# Task-attached records
# ─────────────────────────────────────────────────────────────────────────

class TaskComment(models.Model):
    task = models.ForeignKey(Task, on_delete=models.CASCADE,
                             related_name="comments")
    author_id = models.IntegerField(null=True, blank=True)
    body = models.TextField()

    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())
    updated_at = models.DateTimeField(auto_now=True, db_default=Now())


class TaskAttachment(models.Model):
    """File attached to a task.

    ``file_path`` is the storage key handed back by
    ``apps.media_files.interface.store_file`` (Р3 — no S2S upload call).
    """

    task = models.ForeignKey(Task, on_delete=models.CASCADE,
                             related_name="attachments")
    file_path = models.CharField(max_length=500)
    filename = models.CharField(max_length=255)
    uploaded_by_id = models.IntegerField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())
    updated_at = models.DateTimeField(auto_now=True, db_default=Now())


class TaskActivity(models.Model):
    """Append-only log of task field changes."""

    task = models.ForeignKey(Task, on_delete=models.CASCADE,
                             related_name="activities")
    actor_id = models.IntegerField(null=True, blank=True)
    field_name = models.CharField(max_length=50)
    old_value = models.TextField(null=True, blank=True)
    new_value = models.TextField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())
    updated_at = models.DateTimeField(auto_now=True, db_default=Now())


class TaskLink(models.Model):
    """Directed relationship between two tasks."""

    source = models.ForeignKey(Task, on_delete=models.CASCADE,
                               related_name="outgoing_links")
    target = models.ForeignKey(Task, on_delete=models.CASCADE,
                               related_name="incoming_links")
    link_type = models.CharField(max_length=20, choices=LinkType.choices)
    created_by_id = models.IntegerField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())
    updated_at = models.DateTimeField(auto_now=True, db_default=Now())

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["source", "target", "link_type"],
                                    name="uq_task_link"),
            # The original enforced "no self-link" in the model's __init__,
            # which only covered ORM construction. A CHECK covers every write
            # path — same rule, one layer lower.
            models.CheckConstraint(
                condition=~models.Q(source=models.F("target")),
                name="ck_task_link_not_self",
            ),
        ]


class TaskAssignment(models.Model):
    """Links a task to exactly ONE resource — an employee or a piece of
    equipment.

    Instead of a polymorphic ``(resource_type, resource_id)`` pair the
    original kept two nullable columns plus a CHECK enforcing that exactly
    one is set; that is preserved. ``employee_id`` lost its FK with the user
    replica (Р2); ``equipment`` keeps a real FK since Equipment is local.
    """

    task = models.ForeignKey(Task, on_delete=models.CASCADE,
                             related_name="resource_assignments")
    employee_id = models.IntegerField(null=True, blank=True, db_index=True)
    equipment = models.ForeignKey(Equipment, on_delete=models.CASCADE,
                                  null=True, blank=True,
                                  related_name="assignments")
    role = models.CharField(max_length=100, null=True, blank=True)
    # % of resource capacity, reserved for future overload analysis.
    allocation = models.IntegerField(default=100, db_default=100)

    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())
    updated_at = models.DateTimeField(auto_now=True, db_default=Now())

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(employee_id__isnull=True,
                                   equipment__isnull=False)
                | models.Q(employee_id__isnull=False, equipment__isnull=True),
                name="ck_assignment_exactly_one_resource",
            ),
            models.UniqueConstraint(fields=["task", "employee_id", "equipment"],
                                    name="uq_task_assignment"),
        ]


# ─────────────────────────────────────────────────────────────────────────
# Notifications
# ─────────────────────────────────────────────────────────────────────────

class Notification(models.Model):
    """System notification for task / calendar / HR events.

    ``target_type`` + ``target_id`` is the canonical "click here to see what
    this is about" reference; the frontend maps the type to a route prefix
    (``task`` → /tasks/<id>, ``calendar_event`` → /calendar, ``employee`` →
    /hr/employees/<id>). ``task`` is the legacy FK kept for rows written
    before that generalisation — new code sets ``target_type='task'``.
    """

    recipient_id = models.IntegerField(db_index=True)
    actor_id = models.IntegerField(null=True, blank=True)
    task = models.ForeignKey(Task, on_delete=models.SET_NULL,
                             null=True, blank=True,
                             related_name="notifications")
    verb = models.CharField(max_length=200)
    is_read = models.BooleanField(default=False, db_default=False, db_index=True)
    # Snapshot of the actor's avatar at write time: the original took it so a
    # replica gap couldn't blank the toast's photo. Kept because it is also a
    # point-in-time record — a later avatar change should not rewrite history.
    actor_avatar_url = models.CharField(max_length=1024, null=True, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    target_type = models.CharField(max_length=32, null=True, blank=True)
    target_id = models.IntegerField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())
    updated_at = models.DateTimeField(auto_now=True, db_default=Now())


# ─────────────────────────────────────────────────────────────────────────
# Sequences and the production calendar
# ─────────────────────────────────────────────────────────────────────────

class TaskSequence(models.Model):
    """Atomic counter behind task-key generation (``TASK-17``).

    Incremented under ``select_for_update()`` — see
    ``apps.tasks.services.sequence_service``. The row lock, not this model,
    is what makes concurrent creates collision-free.
    """

    name = models.CharField(max_length=50, unique=True)
    current_value = models.IntegerField(default=0, db_default=0)

    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())
    updated_at = models.DateTimeField(auto_now=True, db_default=Now())


class ProductionDay(models.Model):
    """One day of the production calendar (Kazakhstan).

    ``working_days_since_epoch`` is a running count of working days up to and
    including this date. It turns "deadline = start + N working days" into an
    O(1) indexed lookup instead of a day-by-day walk.
    """

    date = models.DateField(unique=True, db_index=True)
    # working | weekend | holiday | short
    day_type = models.CharField(max_length=20, default="working",
                                db_default="working")
    note = models.CharField(max_length=255, null=True, blank=True)
    working_days_since_epoch = models.IntegerField(db_index=True)

    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())
    updated_at = models.DateTimeField(auto_now=True, db_default=Now())


# ─────────────────────────────────────────────────────────────────────────
# Calendar
# ─────────────────────────────────────────────────────────────────────────

class CalendarEvent(models.Model):
    """Event in the shared calendar.

    Stores precise ``start_at``/``end_at``; ``is_all_day`` is a presentation
    hint — for true all-day events the form sends midnight–end-of-day and the
    UI hides the time component.
    """

    title = models.CharField(max_length=255)
    description = models.TextField(null=True, blank=True)
    start_at = models.DateTimeField(db_index=True)
    end_at = models.DateTimeField(db_index=True)
    is_all_day = models.BooleanField(default=True, db_default=True)
    # personal | department | common | conference
    event_type = models.CharField(max_length=20, default="personal",
                                  db_default="personal", db_index=True)
    conference_room_id = models.CharField(max_length=64, null=True, blank=True)
    color = models.CharField(max_length=20, null=True, blank=True)
    is_global = models.BooleanField(default=False, db_default=False)
    department_id = models.IntegerField(null=True, blank=True, db_index=True)
    # Author, taken from the JWT on create. Nullable so rows predating the
    # column survive a backfill.
    creator_id = models.IntegerField(null=True, blank=True, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())
    updated_at = models.DateTimeField(auto_now=True, db_default=Now())

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(event_type__in=["personal", "department",
                                                   "common", "conference"]),
                name="ck_calendar_event_type",
            ),
            models.CheckConstraint(
                condition=models.Q(end_at__gte=models.F("start_at")),
                name="ck_calendar_event_range",
            ),
        ]


class EventException(models.Model):
    """A cancelled occurrence of a recurring calendar event."""

    event = models.ForeignKey(CalendarEvent, on_delete=models.CASCADE,
                              related_name="exceptions")
    exception_date = models.DateField()
    is_cancelled = models.BooleanField(default=True, db_default=True)

    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())
    updated_at = models.DateTimeField(auto_now=True, db_default=Now())


class CalendarEventParticipant(models.Model):
    """Invitee of a calendar event.

    The original used a composite ``(event_id, user_id)`` primary key. Django
    grows a surrogate ``id`` here and the pair is enforced by a unique
    constraint instead — the pair is never exposed as an identifier by the
    API (participants are addressed by ``user_id`` within an event), so this
    is invisible to clients and keeps the row addressable by the admin.
    """

    event = models.ForeignKey(CalendarEvent, on_delete=models.CASCADE,
                              related_name="participants")
    user_id = models.IntegerField(db_index=True)
    # 'pending' until the invitee responds. The author is inserted as
    # 'accepted' — they implicitly attend their own event.
    rsvp_status = models.CharField(max_length=16, default="pending",
                                   db_default="pending")

    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["event", "user_id"],
                                    name="uq_calendar_event_participant"),
            models.CheckConstraint(
                condition=models.Q(rsvp_status__in=["pending", "accepted",
                                                    "declined"]),
                name="ck_calendar_event_participant_status",
            ),
        ]
