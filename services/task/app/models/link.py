"""Task link (relationship) model."""

import enum
from typing import ClassVar, TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, UniqueConstraint
from sqlalchemy.dialects.postgresql import ENUM as PG_ENUM
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel

if TYPE_CHECKING:
    from .task import Task


class LinkType(enum.StrEnum):
    BLOCKS = "blocks"
    IS_BLOCKED_BY = "is_blocked_by"
    RELATES_TO = "relates_to"
    DUPLICATES = "duplicates"


class TaskLink(BaseModel):
    """Relationship between two tasks."""

    __tablename__ = "task_links"
    __table_args__ = (
        UniqueConstraint("source_id", "target_id", "link_type", name="uq_task_link"),
    )

    source_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tasks.id", ondelete="CASCADE"), index=True
    )
    target_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tasks.id", ondelete="CASCADE"), index=True
    )
    link_type: Mapped[LinkType] = mapped_column(
        PG_ENUM(LinkType, create_type=False, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    created_by_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("task_users.id", ondelete="SET NULL")
    )

    # Relationships
    source: Mapped["Task"] = relationship(
        "Task", foreign_keys=[source_id], back_populates="outgoing_links"
    )
    target: Mapped["Task"] = relationship(
        "Task", foreign_keys=[target_id], back_populates="incoming_links"
    )
    created_by = relationship("User")

    # Denormalized fields for API responses
    source_key: ClassVar[str | None] = None
    source_summary: ClassVar[str | None] = None
    target_key: ClassVar[str | None] = None
    target_summary: ClassVar[str | None] = None

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if self.source_id == self.target_id:
            raise ValueError("Task cannot link to itself")
