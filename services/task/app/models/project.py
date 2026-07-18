"""Project — top-level grouping of tasks for the Roadmap.

Replaces the old ``ProjectVersion`` model (removed in migration 013).
Projects represent durable business initiatives ("Onboarding revamp",
"Q4 expansion to Almaty") rather than software releases — there is no
``release_date`` / ``version`` semantics.

Tasks may optionally belong to a project via ``Task.project_id``.
Tasks **without** a project are standalone work items; this is a
first-class state the UI displays differently from project-attached
tasks. Inside a project the task hierarchy (``parent_id``) is still
honored, so the Roadmap can render a project → top-level task →
subtasks tree.
"""

import enum
from datetime import date
from typing import TYPE_CHECKING, ClassVar

from sqlalchemy import Date, ForeignKey, Integer, String, Text, inspect
from sqlalchemy.dialects.postgresql import ENUM as PG_ENUM
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel

if TYPE_CHECKING:
    from .task import Task
    from .user_replica import User
    from .department_replica import Department


class ProjectStatus(enum.StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class Project(BaseModel):
    """A roadmap-level project that groups tasks."""

    __tablename__ = "projects"

    name: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    status: Mapped[ProjectStatus] = mapped_column(
        PG_ENUM(
            ProjectStatus,
            name="project_status",
            create_type=False,
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        default=ProjectStatus.ACTIVE,
    )
    color: Mapped[str] = mapped_column(String(20), nullable=False, default="#3b82f6", server_default="'#3b82f6'")
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    owner_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("task_users.id", ondelete="SET NULL"), index=True
    )
    department_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("task_departments.id", ondelete="SET NULL"), index=True
    )

    # Relationships
    tasks: Mapped[list["Task"]] = relationship("Task", back_populates="project")
    owner = relationship("User", foreign_keys=[owner_id])
    department = relationship("Department")

    # Aggregated stats — filled by the repository, not stored.
    task_count: ClassVar[int] = 0
    done_count: ClassVar[int] = 0
    progress: ClassVar[float] = 0.0

    @property
    def owner_name(self) -> str | None:
        if "owner" in inspect(self).unloaded:
            return None
        if not self.owner:
            return None
        name = " ".join(p for p in (self.owner.first_name, self.owner.last_name) if p).strip()
        return name or self.owner.username

    @property
    def department_name(self) -> str | None:
        if "department" in inspect(self).unloaded:
            return None
        return self.department.name if self.department else None
