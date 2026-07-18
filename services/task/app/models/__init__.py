"""Task service SQLAlchemy models."""

from .base import Base, BaseModel
from .task import (
    Task,
    Status,
    Priority,
    TaskType,
    TRANSITIONS,
    TERMINAL_STATUSES,
)
from .task_type import TaskTypeRef
from .project import Project, ProjectStatus
from .participants import (
    TaskAssignee,
    TaskDelegate,
    TaskWatcher,
    AssigneeRole,
)
from .sequence import TaskSequence, ProductionDay
from .comment import TaskComment
from .attachment import TaskAttachment
from .link import TaskLink, LinkType
from .activity import TaskActivity
from .label import Label
from .notification import Notification
from .calendar import CalendarEvent, EventException, CalendarEventParticipant
from .user_replica import User
from .department_replica import Department
from .equipment import Equipment
from .assignment import TaskAssignment

__all__ = [
    "Base",
    "BaseModel",
    "Task",
    "TaskTypeRef",
    "Project",
    "ProjectStatus",
    "Equipment",
    "TaskAssignment",
    "TaskSequence",
    "ProductionDay",
    "TaskComment",
    "TaskAttachment",
    "TaskLink",
    "TaskActivity",
    "TaskAssignee",
    "TaskDelegate",
    "TaskWatcher",
    "AssigneeRole",
    "Label",
    "Notification",
    "CalendarEvent",
    "EventException",
    "CalendarEventParticipant",
    "User",
    "Department",
    "Status",
    "Priority",
    "TaskType",
    "LinkType",
    "TRANSITIONS",
    "TERMINAL_STATUSES",
]
