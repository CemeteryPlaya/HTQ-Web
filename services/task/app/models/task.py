"""Task model with FSM status transitions and business logic.

The model intentionally blends Jira and SharePoint semantics:

- Jira side: ``key``, ``task_type`` enum, FSM ``status``, ``links`` (blocks /
  relates_to / duplicates), ``versions`` (release roadmap), ``labels``,
  activity log, hierarchy via ``parent_id``.
- SharePoint side: ``supervisor_id`` (task owner who can delegate),
  delegates (deputies who edit on supervisor's behalf), watchers
  (followers), ``progress_percent``, multi-assignee with primary +
  collaborators roles.
"""

import enum
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    Table,
    Column,
    inspect,
)
from sqlalchemy.dialects.postgresql import ENUM as PG_ENUM
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel

if TYPE_CHECKING:
    from .activity import TaskActivity
    from .attachment import TaskAttachment
    from .comment import TaskComment
    from .link import TaskLink
    from .participants import TaskAssignee, TaskDelegate, TaskWatcher
    from .project import Project
    from .task_type import TaskTypeRef


class Status(enum.StrEnum):
    BACKLOG = "backlog"
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    IN_REVIEW = "in_review"
    BLOCKED = "blocked"
    DONE = "done"
    CANCELLED = "cancelled"


class Priority(enum.StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    TRIVIAL = "trivial"


class TaskType(enum.StrEnum):
    """Legacy enum kept for backward-compat in non-DB call sites.

    The authoritative list of types now lives in the ``task_types`` table
    (see :class:`app.models.task_type.TaskType`). New code should resolve
    types by slug from that table; this enum is only used by callers that
    still type-check against the historical five values.
    """

    TASK = "task"
    BUG = "bug"
    STORY = "story"
    EPIC = "epic"
    SUBTASK = "subtask"


# Terminal statuses — completing or cancelling stamps ``completed_at``.
TERMINAL_STATUSES = {Status.DONE, Status.CANCELLED}


# FSM transitions: from_state -> allowed target states.
# Deliberately permissive: workflow tasks routinely bounce between states
# (e.g. unblock and re-cancel) and a strict graph causes user friction.
TRANSITIONS = {
    Status.BACKLOG: {Status.TODO, Status.IN_PROGRESS, Status.CANCELLED},
    Status.TODO: {Status.IN_PROGRESS, Status.BLOCKED, Status.BACKLOG, Status.CANCELLED},
    Status.IN_PROGRESS: {
        Status.IN_REVIEW,
        Status.BLOCKED,
        Status.DONE,
        Status.TODO,
        Status.CANCELLED,
    },
    Status.IN_REVIEW: {Status.DONE, Status.IN_PROGRESS, Status.BLOCKED, Status.CANCELLED},
    Status.BLOCKED: {Status.IN_PROGRESS, Status.TODO, Status.CANCELLED},
    Status.DONE: {Status.IN_PROGRESS, Status.CANCELLED},  # reopen
    Status.CANCELLED: {Status.BACKLOG, Status.TODO},  # restore from cancel
}


task_labels = Table(
    "task_labels",
    BaseModel.metadata,
    Column("task_id", Integer, ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True),
    Column("label_id", Integer, ForeignKey("labels.id", ondelete="CASCADE"), primary_key=True),
)

# A task may span multiple departments (cross-functional work). The
# single ``department_id`` column remains the primary department; this
# junction holds the full set.
task_department_links = Table(
    "task_department_links",
    BaseModel.metadata,
    Column("task_id", Integer, ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True),
    Column("department_id", Integer, ForeignKey("task_departments.id", ondelete="CASCADE"), primary_key=True),
)


class Task(BaseModel):
    """Main task entity with lifecycle management."""

    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint(
            "start_date IS NULL OR due_date IS NULL OR start_date <= due_date",
            name="ck_task_dates",
        ),
    )

    # Core fields
    key: Mapped[str] = mapped_column(
        String(20), unique=True, nullable=False, index=True
    )
    summary: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", server_default="")

    # Classification — task_type is now FK to the user-configurable
    # task_types table. Nullable so a deletion of a custom type doesn't
    # cascade-delete tasks.
    task_type_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("task_types.id", ondelete="SET NULL"), index=True
    )
    priority: Mapped[Priority] = mapped_column(
        PG_ENUM(Priority, create_type=False, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=Priority.MEDIUM,
    )
    status: Mapped[Status] = mapped_column(
        PG_ENUM(Status, create_type=False, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=Status.TODO,
        index=True,
    )

    # Progress (SharePoint-style %). Independent of status — a task can be
    # 70 % done while still in_review, and 100 % is not auto-Done.
    progress_percent: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0, server_default="0"
    )

    # Assignments — Jira "reporter/assignee" + SharePoint "supervisor"
    reporter_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("task_users.id", ondelete="SET NULL"), index=True
    )
    # ``assignee_id`` stays as a denormalized FK to the **primary** assignee
    # for fast filter/joins and Kanban-card display. Source of truth for
    # the full crew is the ``task_assignees`` junction table.
    assignee_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("task_users.id", ondelete="SET NULL"), index=True
    )
    supervisor_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("task_users.id", ondelete="SET NULL"), index=True
    )
    department_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("task_departments.id", ondelete="SET NULL"), index=True
    )
    # Optional roadmap project. NULL means the task is "standalone" —
    # a state that is intentionally first-class in the UI: standalone
    # tasks are listed without a project chip and don't appear under any
    # project on the Roadmap.
    project_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("projects.id", ondelete="SET NULL"), index=True
    )

    # Hierarchy
    parent_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("tasks.id", ondelete="SET NULL"), index=True
    )

    # Dates
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    estimated_working_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Soft delete (mirrors Django SoftDeleteMixin)
    is_deleted: Mapped[bool] = mapped_column(
        default=False, server_default="false", index=True
    )

    # Relationships
    reporter = relationship("User", foreign_keys=[reporter_id])
    assignee = relationship("User", foreign_keys=[assignee_id])
    supervisor = relationship("User", foreign_keys=[supervisor_id])
    department = relationship("Department", foreign_keys=[department_id])
    departments = relationship("Department", secondary=task_department_links)
    project = relationship("Project", back_populates="tasks")
    task_type_ref = relationship("TaskTypeRef", back_populates="tasks")
    parent = relationship("Task", remote_side="Task.id", backref="subtasks")

    # Multi-assignee, delegation, watcher relationships (see participants.py)
    assignees: Mapped[list["TaskAssignee"]] = relationship(
        "TaskAssignee", back_populates="task", cascade="all, delete-orphan"
    )
    delegates: Mapped[list["TaskDelegate"]] = relationship(
        "TaskDelegate", back_populates="task", cascade="all, delete-orphan"
    )
    watchers: Mapped[list["TaskWatcher"]] = relationship(
        "TaskWatcher", back_populates="task", cascade="all, delete-orphan"
    )

    comments: Mapped[list["TaskComment"]] = relationship(
        "TaskComment", back_populates="task", cascade="all, delete-orphan"
    )
    attachments: Mapped[list["TaskAttachment"]] = relationship(
        "TaskAttachment", back_populates="task", cascade="all, delete-orphan"
    )
    activities: Mapped[list["TaskActivity"]] = relationship(
        "TaskActivity", back_populates="task", cascade="all, delete-orphan"
    )
    outgoing_links: Mapped[list["TaskLink"]] = relationship(
        "TaskLink",
        foreign_keys="TaskLink.source_id",
        back_populates="source",
        cascade="all, delete-orphan",
    )
    incoming_links: Mapped[list["TaskLink"]] = relationship(
        "TaskLink",
        foreign_keys="TaskLink.target_id",
        back_populates="target",
        cascade="all, delete-orphan",
    )

    labels = relationship(
        "Label",
        secondary="task_labels",
        back_populates="tasks",
    )

    # FSM validation
    def can_transition_to(self, target: Status) -> bool:
        """Check if task can transition to target status."""
        return target in TRANSITIONS.get(self.status, set())

    def apply_transition(self, target: Status) -> None:
        """Apply status transition with validation."""
        if not self.can_transition_to(target):
            raise ValueError(
                f"Cannot transition from {self.status} to {target}. "
                f"Allowed: {TRANSITIONS.get(self.status, set())}"
            )
        self.status = target
        if target in TERMINAL_STATUSES and not self.completed_at:
            self.completed_at = datetime.utcnow()
        elif target not in TERMINAL_STATUSES:
            # Re-opened — clear the completion stamp so analytics are honest.
            self.completed_at = None
        if target == Status.DONE:
            self.progress_percent = 100

    @staticmethod
    def _display_user(user) -> str | None:
        if not user:
            return None
        name = " ".join(part for part in (user.first_name, user.last_name) if part).strip()
        return name or user.username

    def _is_loaded(self, relationship_name: str) -> bool:
        return relationship_name not in inspect(self).unloaded

    @property
    def reporter_name(self) -> str | None:
        if not self._is_loaded("reporter"):
            return None
        return self._display_user(self.reporter)

    @property
    def assignee_name(self) -> str | None:
        if not self._is_loaded("assignee"):
            return None
        return self._display_user(self.assignee)

    @property
    def supervisor_name(self) -> str | None:
        if not self._is_loaded("supervisor"):
            return None
        return self._display_user(self.supervisor)

    @property
    def department_name(self) -> str | None:
        if not self._is_loaded("department"):
            return None
        return self.department.name if self.department else None

    @property
    def department_ids(self) -> list[int]:
        if not self._is_loaded("departments"):
            return []
        return [d.id for d in (self.departments or [])]

    @property
    def department_names(self) -> list[str]:
        if not self._is_loaded("departments"):
            return []
        return [d.name for d in (self.departments or [])]

    @property
    def project_name(self) -> str | None:
        if not self._is_loaded("project"):
            return None
        return self.project.name if self.project else None

    @property
    def project_color(self) -> str | None:
        if not self._is_loaded("project"):
            return None
        return self.project.color if self.project else None

    @property
    def task_type(self) -> str:
        """Backward-compat: expose the type slug as ``task_type`` for
        existing API consumers that expect a string like 'task'/'bug'."""
        if not self._is_loaded("task_type_ref"):
            return "task"
        return self.task_type_ref.slug if self.task_type_ref else "task"

    @property
    def task_type_name(self) -> str | None:
        if not self._is_loaded("task_type_ref"):
            return None
        return self.task_type_ref.name if self.task_type_ref else None

    @property
    def task_type_color(self) -> str | None:
        if not self._is_loaded("task_type_ref"):
            return None
        return self.task_type_ref.color if self.task_type_ref else None

    @property
    def parent_key(self) -> str | None:
        if not self._is_loaded("parent"):
            return None
        return self.parent.key if self.parent else None

    @property
    def subtask_count(self) -> int:
        if not self._is_loaded("subtasks"):
            return 0
        return len(self.subtasks or [])

    @property
    def label_ids(self) -> list[int]:
        if not self._is_loaded("labels"):
            return []
        return [label.id for label in (self.labels or [])]
