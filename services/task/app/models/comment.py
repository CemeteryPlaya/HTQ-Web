"""Task comment model."""

from typing import ClassVar, TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel

if TYPE_CHECKING:
    from .task import Task


class TaskComment(BaseModel):
    """Comment on a task."""

    __tablename__ = "task_comments"

    task_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tasks.id", ondelete="CASCADE"), index=True
    )
    author_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("task_users.id", ondelete="SET NULL")
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)

    # Relationships
    task: Mapped["Task"] = relationship("Task", back_populates="comments")
    author = relationship("User")

    # Denormalized fields for API responses
    author_name: ClassVar[str | None] = None
