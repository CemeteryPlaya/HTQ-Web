"""Pydantic schemas for task service API."""

from .common import DateWarning, PaginatedResponse
from .label import LabelCreate, LabelUpdate, LabelResponse
from .project import ProjectCreate, ProjectUpdate, ProjectResponse
from .task_type import TaskTypeCreate, TaskTypeUpdate, TaskTypeResponse
from .task import (
    TaskCreate,
    TaskUpdate,
    TaskListResponse,
    TaskDetailResponse,
    AssigneeAssignment,
    AssigneeResponse,
    AssigneesUpdate,
    DelegateCreate,
    DelegateResponse,
    SupervisorUpdate,
    WatcherResponse,
    ProgressUpdate,
)
from .comment import CommentCreate, CommentUpdate, CommentResponse
from .attachment import AttachmentResponse
from .link import LinkCreate, LinkResponse, LinkType
from .activity import ActivityResponse
from .notification import NotificationResponse
from .calendar import (
    CalendarEventBase,
    CalendarEventCreate,
    CalendarEventUpdate,
    CalendarEventResponse,
    EventExceptionBase,
    EventExceptionResponse,
    ProductionDayResponse,
    ProductionDayUpdate,
)

__all__ = [
    "DateWarning",
    "PaginatedResponse",
    "LabelCreate",
    "LabelUpdate",
    "LabelResponse",
    "ProjectCreate",
    "ProjectUpdate",
    "ProjectResponse",
    "TaskTypeCreate",
    "TaskTypeUpdate",
    "TaskTypeResponse",
    "TaskCreate",
    "TaskUpdate",
    "TaskListResponse",
    "TaskDetailResponse",
    "AssigneeAssignment",
    "AssigneeResponse",
    "AssigneesUpdate",
    "DelegateCreate",
    "DelegateResponse",
    "SupervisorUpdate",
    "WatcherResponse",
    "ProgressUpdate",
    "CommentCreate",
    "CommentUpdate",
    "CommentResponse",
    "AttachmentResponse",
    "LinkCreate",
    "LinkResponse",
    "LinkType",
    "ActivityResponse",
    "NotificationResponse",
    "CalendarEventBase",
    "CalendarEventCreate",
    "CalendarEventUpdate",
    "CalendarEventResponse",
    "EventExceptionBase",
    "EventExceptionResponse",
    "ProductionDayResponse",
    "ProductionDayUpdate",
]
