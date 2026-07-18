"""Task attachment model."""

from typing import ClassVar, TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel

if TYPE_CHECKING:
    from .task import Task


class TaskAttachment(BaseModel):
    """File attachment for a task."""

    __tablename__ = "task_attachments"

    task_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tasks.id", ondelete="CASCADE"), index=True
    )
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    uploaded_by_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("task_users.id", ondelete="SET NULL")
    )

    # Relationships
    task: Mapped["Task"] = relationship("Task", back_populates="attachments")
    uploaded_by = relationship("User")

    # Denormalized fields for API responses
    uploaded_by_name: ClassVar[str | None] = None
