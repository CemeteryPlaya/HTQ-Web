"""Pydantic schemas for the tasks domain.

Ported from ``services/task/app/schemas/*.py``. Per PLAN.md §3 the schemas
come across as-is — they ARE the response contract, and the whole point of
the port is that a client cannot tell which backend answered. Where the
original imported a SQLAlchemy enum (``Status``, ``Priority``,
``ProjectStatus``, ``LinkType``, ``AssigneeRole``) this imports the
equivalent ``TextChoices`` from ``apps.tasks.models``; both serialise to the
same string values, so the wire format is unchanged.

Two shape decisions worth stating, because they look like drift and are not:

* ``TaskListResponse``/``TaskDetailResponse`` keep every denormalised
  ``*_name`` field (``assignee_name``, ``department_name``, …). The original
  filled them from SQLAlchemy relationship properties on the replica tables;
  with the replicas gone (Р2) they are filled by
  ``apps.tasks.services.hydration``. Same fields, same nullability — a
  missing user still yields ``None``, exactly as a lagging replica did.
* ``LinkResponse.created_at`` is typed ``str``, not ``datetime``. That is
  what the FastAPI original declares, and pydantic therefore emitted the
  ``str()`` of the datetime rather than an ISO-8601 ``datetime``. Kept
  deliberately: "byte-for-byte" beats "more correct" here.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from .models import AssigneeRole, LinkType, Priority, ProjectStatus, Status


# ── common ──────────────────────────────────────────────────────────────

class DateWarning(BaseModel):
    """Date-calculation warning attached to a task response."""

    code: str
    message: str


# ── labels ──────────────────────────────────────────────────────────────

class LabelCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    color: str = Field(default="#808080", pattern=r"^#[0-9A-Fa-f]{6}$")


class LabelUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    color: str | None = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$")


class LabelResponse(BaseModel):
    id: int
    name: str
    color: str

    model_config = {"from_attributes": True}


# ── task types ──────────────────────────────────────────────────────────

SLUG_RE = re.compile(r"^[a-z0-9_-]+$")


class TaskTypeCreate(BaseModel):
    # Optional — when omitted the service auto-generates it from ``name``
    # (transliterating Cyrillic and de-duplicating).
    slug: str | None = Field(default=None, max_length=50)
    name: str = Field(..., min_length=1, max_length=100)
    color: str = Field(default="#6b7280", max_length=20)
    icon: str | None = Field(default=None, max_length=50)

    @field_validator("slug")
    @classmethod
    def slug_format(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip().lower()
        if not v:
            return None
        if not SLUG_RE.match(v):
            raise ValueError("Slug must contain only lowercase letters, digits, _ and -")
        return v


class TaskTypeUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    color: str | None = Field(None, max_length=20)
    icon: str | None = Field(None, max_length=50)
    # slug is intentionally NOT editable — it is the stable identifier the
    # historical UI and the phase-10 ETL both key on.


class TaskTypeResponse(BaseModel):
    id: int
    slug: str
    name: str
    color: str
    icon: str | None = None
    is_system: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── comments / attachments / activity ───────────────────────────────────

class CommentCreate(BaseModel):
    body: str = Field(..., min_length=1, max_length=10000)

    @field_validator("body")
    @classmethod
    def body_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Comment body cannot be blank")
        return v


class CommentUpdate(BaseModel):
    body: str = Field(..., min_length=1, max_length=10000)


class CommentResponse(BaseModel):
    id: int
    task_id: int
    author_id: int | None = None
    author_name: str | None = None
    body: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AttachmentResponse(BaseModel):
    id: int
    task_id: int
    file_path: str
    filename: str
    uploaded_by_id: int | None = None
    uploaded_by_name: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ActivityResponse(BaseModel):
    id: int
    task_id: int
    actor_id: int | None = None
    actor_name: str | None = None
    field_name: str
    old_value: str | None = None
    new_value: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── links ───────────────────────────────────────────────────────────────

class LinkCreate(BaseModel):
    source_id: int
    target_id: int
    link_type: LinkType

    @model_validator(mode="after")
    def prevent_self_reference(self) -> "LinkCreate":
        if self.source_id == self.target_id:
            raise ValueError("Task cannot link to itself")
        return self


class LinkResponse(BaseModel):
    id: int
    source_id: int
    target_id: int
    link_type: LinkType
    created_by_id: int | None = None

    source_key: str | None = None
    source_summary: str | None = None
    target_key: str | None = None
    target_summary: str | None = None

    # ``str``, not ``datetime`` — see the module docstring.
    created_at: str

    model_config = {"from_attributes": True}


# ── projects ────────────────────────────────────────────────────────────

class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="", max_length=5000)
    status: ProjectStatus = Field(default=ProjectStatus.ACTIVE)
    color: str = Field(default="#3b82f6", max_length=20)
    start_date: date | None = None
    end_date: date | None = None
    owner_id: int | None = None
    department_id: int | None = None


class ProjectUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = Field(None, max_length=5000)
    status: ProjectStatus | None = None
    color: str | None = Field(None, max_length=20)
    start_date: date | None = None
    end_date: date | None = None
    owner_id: int | None = None
    department_id: int | None = None


class ProjectResponse(BaseModel):
    id: int
    name: str
    description: str
    status: ProjectStatus
    color: str
    start_date: date | None
    end_date: date | None
    owner_id: int | None = None
    owner_name: str | None = None
    department_id: int | None = None
    department_name: str | None = None
    task_count: int = 0
    done_count: int = 0
    progress: float = 0.0
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── tasks ───────────────────────────────────────────────────────────────

class DepartmentRef(BaseModel):
    """Compact department reference for multi-department task responses."""

    id: int
    name: str

    model_config = {"from_attributes": True}


class AssigneeAssignment(BaseModel):
    """One row of the task-assignee junction, as sent by a client."""

    user_id: int
    role: AssigneeRole = AssigneeRole.COLLABORATOR


class AssigneeResponse(BaseModel):
    user_id: int
    role: AssigneeRole
    name: str | None = None
    avatar_url: str | None = None

    model_config = {"from_attributes": True}


class DelegateResponse(BaseModel):
    user_id: int
    name: str | None = None
    avatar_url: str | None = None
    granted_by_id: int | None = None
    granted_by_name: str | None = None
    granted_at: datetime | None = None

    model_config = {"from_attributes": True}


class WatcherResponse(BaseModel):
    user_id: int
    name: str | None = None
    avatar_url: str | None = None

    model_config = {"from_attributes": True}


class TaskCreate(BaseModel):
    summary: str = Field(..., min_length=1, max_length=500)
    description: str = Field(default="", max_length=10000)
    # Type by FK to the registry, or by slug (resolved server-side). The
    # legacy ``task_type`` string is also accepted for backward-compat.
    task_type_id: int | None = None
    task_type: str | None = None
    priority: Priority = Field(default=Priority.MEDIUM)
    status: Status = Field(default=Status.TODO)

    reporter_id: int | None = None
    supervisor_id: int | None = None
    department_id: int | None = None
    # Multi-department. The first id (or ``department_id``) becomes the
    # primary; the full set is persisted in the junction.
    department_ids: list[int] = Field(default_factory=list)
    # None means a standalone task — explicitly chosen in the create dialog.
    project_id: int | None = None
    parent_id: int | None = None

    # If both ``assignee_id`` (legacy) and ``assignees`` arrive, the service
    # builds the final crew by union.
    assignee_id: int | None = None
    assignees: list[AssigneeAssignment] = Field(default_factory=list)

    label_ids: list[int] = Field(default_factory=list)

    progress_percent: int = Field(default=0, ge=0, le=100)
    due_date: date | None = None
    start_date: date | None = None
    estimated_working_days: int | None = None

    @field_validator("summary")
    @classmethod
    def summary_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Summary cannot be blank")
        return v


class TaskUpdate(BaseModel):
    """Partial update. Unset fields are left alone (``exclude_unset``).

    ``assignees`` / ``delegates`` / ``watchers`` have dedicated endpoints and
    are read-only here.
    """

    summary: str | None = Field(None, min_length=1, max_length=500)
    description: str | None = Field(None, max_length=10000)
    task_type_id: int | None = None
    task_type: str | None = None
    priority: Priority | None = None
    status: Status | None = None

    reporter_id: int | None = None
    assignee_id: int | None = None
    supervisor_id: int | None = None
    department_id: int | None = None
    department_ids: list[int] | None = None
    project_id: int | None = None
    parent_id: int | None = None

    label_ids: list[int] | None = None

    progress_percent: int | None = Field(None, ge=0, le=100)
    due_date: date | None = None
    start_date: date | None = None
    estimated_working_days: int | None = None


class AssigneesUpdate(BaseModel):
    """Body for PATCH /tasks/{id}/assignees/ — replaces the whole crew."""

    assignees: list[AssigneeAssignment]

    @field_validator("assignees")
    @classmethod
    def at_most_one_primary(cls, v: list[AssigneeAssignment]) -> list[AssigneeAssignment]:
        primaries = [a for a in v if a.role == AssigneeRole.PRIMARY]
        if len(primaries) > 1:
            raise ValueError("At most one assignee may have role=primary")
        return v


class SupervisorUpdate(BaseModel):
    user_id: int | None = None


class DelegateCreate(BaseModel):
    user_id: int


class ProgressUpdate(BaseModel):
    percent: int = Field(..., ge=0, le=100)


class TaskListResponse(BaseModel):
    """Compact task response for list views."""

    id: int
    key: str
    summary: str
    # ``task_type`` carries the slug of the related registry row;
    # ``task_type_id`` is the FK for clients that edit by id.
    task_type_id: int | None = None
    task_type: str = "task"
    task_type_name: str | None = None
    task_type_color: str | None = None
    priority: Priority
    status: Status
    progress_percent: int = 0

    reporter_id: int | None = None
    reporter_name: str | None = None
    assignee_id: int | None = None
    assignee_name: str | None = None
    supervisor_id: int | None = None
    supervisor_name: str | None = None
    department_id: int | None = None
    department_name: str | None = None
    department_ids: list[int] = []
    departments: list[DepartmentRef] = []
    project_id: int | None = None
    project_name: str | None = None
    project_color: str | None = None
    parent_id: int | None = None
    parent_key: str | None = None

    assignees: list[AssigneeResponse] = []
    labels: list[LabelResponse] = []
    due_date: date | None = None
    start_date: date | None = None
    effective_start_date: date | None = None
    effective_due_date: date | None = None
    date_warnings: list[DateWarning] = []
    completed_at: datetime | None = None

    subtask_count: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TaskDetailResponse(BaseModel):
    """Detailed task response with nested data."""

    id: int
    key: str
    summary: str
    description: str
    task_type_id: int | None = None
    task_type: str = "task"
    task_type_name: str | None = None
    task_type_color: str | None = None
    priority: Priority
    status: Status
    progress_percent: int = 0

    reporter_id: int | None = None
    reporter_name: str | None = None
    assignee_id: int | None = None
    assignee_name: str | None = None
    supervisor_id: int | None = None
    supervisor_name: str | None = None
    department_id: int | None = None
    department_name: str | None = None
    department_ids: list[int] = []
    departments: list[DepartmentRef] = []
    project_id: int | None = None
    project_name: str | None = None
    project_color: str | None = None
    parent_id: int | None = None
    parent_key: str | None = None

    assignees: list[AssigneeResponse] = []
    delegates: list[DelegateResponse] = []
    watchers: list[WatcherResponse] = []

    labels: list[LabelResponse] = []
    label_ids: list[int] = Field(default=[], description="Write-only label IDs")

    due_date: date | None = None
    start_date: date | None = None
    effective_start_date: date | None = None
    effective_due_date: date | None = None
    date_warnings: list[DateWarning] = []
    completed_at: datetime | None = None

    comments: list[CommentResponse] = []
    attachments: list[AttachmentResponse] = []
    subtasks: list["TaskListResponse"] = []
    activities: list[ActivityResponse] = []
    outgoing_links: list[LinkResponse] = []
    incoming_links: list[LinkResponse] = []

    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TaskStats(BaseModel):
    total: int
    by_status: dict[str, int]
    by_priority: dict[str, int]
    by_type: dict[str, int]
    by_department: list[dict]
    by_assignee: list[dict]
    created_per_day: list[dict]
    resolved_per_day: list[dict]


# ── notifications ───────────────────────────────────────────────────────

class NotificationResponse(BaseModel):
    """``target_type`` + ``target_id`` is the canonical "click here"
    reference; the frontend maps the type to a route, so the backend stays
    free of UI knowledge. ``task_key`` is filled when the row references a
    task (legacy ``task_id`` FK OR ``target_type='task'``) so the dropdown
    can show «В задаче: ABC-123» without a second roundtrip."""

    id: int
    recipient_id: int
    actor_id: int | None = None
    actor_name: str | None = None
    actor_avatar_url: str | None = None
    verb: str
    task_id: int | None = None
    task_key: str | None = None
    target_type: str | None = None
    target_id: int | None = None
    is_read: bool
    read_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class NotificationsPage(BaseModel):
    items: list[NotificationResponse]
    total: int
    page: int
    pages: int
    limit: int
    unread_total: int


# ── gantt / equipment / assignments ─────────────────────────────────────

class GanttTask(BaseModel):
    """One bar in the report Gantt. Flat list; hierarchy via ``parent``."""

    id: str
    key: str
    text: str
    start_date: date | None = None
    end_date: date | None = None
    progress: float = 0.0
    status: str
    parent: str | None = None
    assignees: list[str] = []


class ReportsGanttResponse(BaseModel):
    tasks: list[GanttTask]


class AllocatedTask(BaseModel):
    task_id: str
    key: str
    title: str
    start_date: date | None = None
    end_date: date | None = None
    progress: float = 0.0
    status: str
    allocation: int = 100


class ResourceRow(BaseModel):
    resource_id: str                 # e.g. "emp_8" / "eq_3"
    resource_kind: str               # "employee" | "equipment"
    resource_name: str
    meta: dict = Field(default_factory=dict)
    allocated_tasks: list[AllocatedTask] = []


class ResourceGanttResponse(BaseModel):
    range: dict
    resources: list[ResourceRow]


class EquipmentCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    inventory_no: str | None = Field(None, max_length=50)
    category: str | None = Field(None, max_length=100)


class EquipmentUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    inventory_no: str | None = Field(None, max_length=50)
    category: str | None = Field(None, max_length=100)
    is_active: bool | None = None


class EquipmentResponse(BaseModel):
    id: int
    name: str
    inventory_no: str | None = None
    category: str | None = None
    is_active: bool

    model_config = {"from_attributes": True}


class AssignmentCreate(BaseModel):
    task_id: int
    employee_id: int | None = None
    equipment_id: int | None = None
    role: str | None = Field(None, max_length=100)
    allocation: int = Field(100, ge=0, le=100)


class AssignmentResponse(BaseModel):
    id: int
    task_id: int
    employee_id: int | None = None
    equipment_id: int | None = None
    role: str | None = None
    allocation: int

    model_config = {"from_attributes": True}


# ── calendar ────────────────────────────────────────────────────────────

EventType = Literal["personal", "department", "common", "conference"]
RsvpStatus = Literal["pending", "accepted", "declined"]
DayType = Literal["working", "weekend", "holiday", "short"]


class EventExceptionBase(BaseModel):
    exception_date: date
    is_cancelled: bool = True


class EventExceptionResponse(EventExceptionBase):
    id: int
    event_id: int

    model_config = {"from_attributes": True}


class CalendarEventBase(BaseModel):
    title: str
    description: str | None = None
    # Precise timestamps. For all-day events the form sends midnight in the
    # user's local tz with ``is_all_day=True``; the UI hides the time.
    start_at: datetime
    end_at: datetime
    is_all_day: bool = True
    event_type: EventType = "personal"
    conference_room_id: str | None = None
    color: str | None = None
    is_global: bool = False
    department_id: int | None = None


class CalendarEventCreate(CalendarEventBase):
    # Users to invite besides the creator. The event then appears on each of
    # their calendars without needing ``is_global``.
    participant_user_ids: list[int] = []

    @field_validator("end_at")
    @classmethod
    def end_after_start(cls, v: datetime, info):
        start = info.data.get("start_at")
        if start is not None and v < start:
            raise ValueError("end_at must be >= start_at")
        return v


class CalendarEventUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    is_all_day: bool | None = None
    event_type: EventType | None = None
    conference_room_id: str | None = None
    color: str | None = None
    is_global: bool | None = None
    department_id: int | None = None
    # ``None`` means "do not touch participants"; an empty list clears them.
    participant_user_ids: list[int] | None = None


class CalendarEventParticipantInfo(BaseModel):
    user_id: int
    full_name: str | None = None
    email: str | None = None
    avatar_url: str | None = None
    rsvp_status: RsvpStatus = "pending"


class CalendarEventResponse(CalendarEventBase):
    id: int
    created_at: datetime
    updated_at: datetime
    creator_id: int | None = None
    exceptions: list[EventExceptionResponse] = []
    participants: list[CalendarEventParticipantInfo] = []

    model_config = {"from_attributes": True}


class RsvpUpdate(BaseModel):
    status: RsvpStatus


class ProductionDayUpdate(BaseModel):
    day_type: DayType
    note: str | None = None


class ProductionDayResponse(BaseModel):
    date: date
    day_type: DayType
    working_days_since_epoch: int
    note: str | None = None

    model_config = {"from_attributes": True}
