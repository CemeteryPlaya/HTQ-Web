"""Notification model for task-related alerts."""

from datetime import datetime
from typing import ClassVar, TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel

if TYPE_CHECKING:
    from .task import Task


class Notification(BaseModel):
    """System notification for task / calendar / HR events.

    The ``target_type`` + ``target_id`` pair is the canonical "click here
    to see what this is about" reference. The frontend maps the type to a
    route prefix:

    - ``task``            → ``/tasks/<id>``
    - ``calendar_event``  → ``/calendar`` (anchored to the event)
    - ``employee``        → ``/hr/employees/<id>``

    ``task_id`` is kept for backwards compat with rows created before
    migration 009 — new code should set ``target_type='task'`` instead.
    """

    __tablename__ = "notifications"

    recipient_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("task_users.id", ondelete="CASCADE"), index=True
    )
    actor_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("task_users.id", ondelete="SET NULL"), nullable=True
    )
    task_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True
    )
    verb: Mapped[str] = mapped_column(String(200), nullable=False)
    is_read: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", index=True
    )
    # Snapshot of the actor's avatar URL at the moment this notification
    # was written. Survives replica gaps — if ``task_users.avatar_url``
    # is empty for the actor, the toast still has a stable photo to show.
    actor_avatar_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    # Timestamp the user marked this as read. Stays NULL until then —
    # the history page renders «—» for unread rows and «12 мая, 14:31»
    # otherwise.
    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Generic target. ``task_id`` above is kept as the legacy/FK column.
    target_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    target_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Relationships
    recipient = relationship("User", foreign_keys=[recipient_id])
    actor = relationship("User", foreign_keys=[actor_id])
    task: Mapped["Task | None"] = relationship("Task")

    # Denormalized fields for API responses
    actor_name: ClassVar[str | None] = None
    task_key: ClassVar[str | None] = None
