"""Task activity log model."""

from typing import ClassVar, TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel

if TYPE_CHECKING:
    from .task import Task


class TaskActivity(BaseModel):
    """Activity log for task field changes."""

    __tablename__ = "task_activities"

    task_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tasks.id", ondelete="CASCADE"), index=True
    )
    actor_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("task_users.id", ondelete="SET NULL")
    )
    field_name: Mapped[str] = mapped_column(String(50), nullable=False)
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    task: Mapped["Task"] = relationship("Task", back_populates="activities")
    actor = relationship("User")

    # Denormalized fields for API responses
    actor_name: ClassVar[str | None] = None
