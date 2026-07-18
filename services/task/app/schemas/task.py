"""Task schemas — Jira + SharePoint shape.

Notable additions vs. the original dev-team model:

- ``supervisor_id`` (single)              — task owner who can delegate
- ``assignees: list[AssigneeAssignment]`` — multi-assignee with role
- ``delegates: list[DelegateAssignment]`` — supervisor's deputies (read)
- ``watchers: list[WatcherAssignment]``   — followers (read)
- ``progress_percent`` (0..100)           — SharePoint-style progress
- expanded ``Status`` enum (7 values)
"""

from datetime import date, datetime

from pydantic import BaseModel, Field, field_validator

from app.models.task import Status, Priority
from app.models.participants import AssigneeRole
from app.schemas.label import LabelResponse
from app.schemas.comment import CommentResponse
from app.schemas.attachment import AttachmentResponse
from app.schemas.activity import ActivityResponse
from app.schemas.link import LinkResponse
from app.schemas.common import DateWarning


class DepartmentRef(BaseModel):
    """Compact department reference for multi-department task responses."""

    id: int
    name: str

    model_config = {"from_attributes": True}


class AssigneeAssignment(BaseModel):
    """One row of the task_assignees junction."""

    user_id: int
    role: AssigneeRole = AssigneeRole.COLLABORATOR


class AssigneeResponse(BaseModel):
    """task_assignees row enriched with the user's display name."""

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
    """Schema for creating a task."""

    summary: str = Field(..., min_length=1, max_length=500)
    description: str = Field(default="", max_length=10000)
    # Type by FK to ``task_types``; or by slug (resolved server-side).
    # The legacy ``task_type`` string is also accepted for backward-compat.
    task_type_id: int | None = None
    task_type: str | None = None
    priority: Priority = Field(default=Priority.MEDIUM)
    status: Status = Field(default=Status.TODO)

    reporter_id: int | None = None
    supervisor_id: int | None = None
    department_id: int | None = None
    # Multi-department. The first id (or ``department_id``) becomes the
    # primary department; the full set is persisted in the junction.
    department_ids: list[int] = Field(default_factory=list)
    # Project linkage. None means a standalone task — explicitly chosen
    # by the user in the create dialog.
    project_id: int | None = None
    parent_id: int | None = None

    # Multi-assignee. If both ``assignee_id`` (legacy) and ``assignees``
    # arrive, the service builds the final crew by union (assignee_id
    # becomes primary, the explicit list adds the rest).
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
    """Schema for updating a task.

    Fields default to ``None`` (unset). Use ``model_dump(exclude_unset=True)``
    to apply partial updates. ``assignees`` / ``delegates`` / ``watchers``
    have their own dedicated endpoints — they are read-only here.
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
    """Body for PATCH /tasks/{id}/assignees — replaces the whole crew."""

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
    # Backward-compat shape: ``task_type`` carries the slug from the
    # related TaskTypeRef row. ``task_type_id`` is the FK for clients
    # that want to edit by id.
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
    """Task statistics."""

    total: int
    by_status: dict[str, int]
    by_priority: dict[str, int]
    by_type: dict[str, int]
    by_department: list[dict]
    by_assignee: list[dict]
    created_per_day: list[dict]
    resolved_per_day: list[dict]
