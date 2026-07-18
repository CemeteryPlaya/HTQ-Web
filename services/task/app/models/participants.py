"""Task participant models — multi-assignee, delegates, watchers.

These three lightweight junction tables together implement the SharePoint
side of the task model (see services/task/app/models/task.py docstring):

- ``task_assignees``  — multiple workers on one task with a role
  (``primary`` / ``collaborator``). The primary is mirrored to
  ``tasks.assignee_id`` for fast filter/joins and Kanban-card avatars.
- ``task_delegates``  — deputies authorised by the supervisor to edit on
  their behalf. Carries who-granted-it and when so the audit trail in
  ``TaskActivity`` can attribute changes to a delegate vs. the supervisor.
- ``task_watchers``   — followers / subscribers. No edit rights, but they
  see the task in their lists and receive notifications.
"""

import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, UniqueConstraint, func, inspect
from sqlalchemy.dialects.postgresql import ENUM as PG_ENUM
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from .task import Task
    from .user_replica import User


def _display_user_name(user) -> str | None:
    if not user:
        return None
    name = " ".join(part for part in (user.first_name, user.last_name) if part).strip()
    return name or user.username


def _user_loaded(instance, attr: str) -> bool:
    return attr not in inspect(instance).unloaded


class AssigneeRole(enum.StrEnum):
    PRIMARY = "primary"
    COLLABORATOR = "collaborator"


class TaskAssignee(Base):
    """M:M between tasks and users with a role."""

    __tablename__ = "task_assignees"
    __table_args__ = (
        UniqueConstraint("task_id", "user_id", name="uq_task_assignee"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tasks.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("task_users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    role: Mapped[AssigneeRole] = mapped_column(
        PG_ENUM(
            AssigneeRole,
            name="task_assignee_role",
            create_type=False,
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        default=AssigneeRole.COLLABORATOR,
    )
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    task: Mapped["Task"] = relationship("Task", back_populates="assignees")
    user: Mapped["User"] = relationship("User")

    @property
    def name(self) -> str | None:
        if not _user_loaded(self, "user"):
            return None
        return _display_user_name(self.user)

    @property
    def avatar_url(self) -> str | None:
        if not _user_loaded(self, "user"):
            return None
        return self.user.avatar_url if self.user else None


class TaskDelegate(Base):
    """Supervisor's deputy on a task.

    Anyone listed here may edit the task as if they were the supervisor.
    ``granted_by`` is who created the delegation (almost always the
    supervisor — but ``is_elevated`` admins can also push a delegate).
    """

    __tablename__ = "task_delegates"
    __table_args__ = (
        UniqueConstraint("task_id", "user_id", name="uq_task_delegate"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tasks.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("task_users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    granted_by_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("task_users.id", ondelete="SET NULL"), nullable=True
    )
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    task: Mapped["Task"] = relationship("Task", back_populates="delegates")
    user: Mapped["User"] = relationship("User", foreign_keys=[user_id])
    granted_by: Mapped["User | None"] = relationship(
        "User", foreign_keys=[granted_by_id]
    )

    @property
    def name(self) -> str | None:
        if not _user_loaded(self, "user"):
            return None
        return _display_user_name(self.user)

    @property
    def avatar_url(self) -> str | None:
        if not _user_loaded(self, "user"):
            return None
        return self.user.avatar_url if self.user else None

    @property
    def granted_by_name(self) -> str | None:
        if not _user_loaded(self, "granted_by"):
            return None
        return _display_user_name(self.granted_by)


class TaskWatcher(Base):
    """User following a task — receives notifications, sees it in lists."""

    __tablename__ = "task_watchers"
    __table_args__ = (
        UniqueConstraint("task_id", "user_id", name="uq_task_watcher"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tasks.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("task_users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    subscribed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    task: Mapped["Task"] = relationship("Task", back_populates="watchers")
    user: Mapped["User"] = relationship("User")

    @property
    def name(self) -> str | None:
        if not _user_loaded(self, "user"):
            return None
        return _display_user_name(self.user)

    @property
    def avatar_url(self) -> str | None:
        if not _user_loaded(self, "user"):
            return None
        return self.user.avatar_url if self.user else None
