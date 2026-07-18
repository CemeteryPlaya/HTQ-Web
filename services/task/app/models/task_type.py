"""TaskType registry — DB-backed replacement for the legacy PG enum.

Different business domains have wildly different vocabularies for
"what kind of work is this": dev teams talk about ``bug`` / ``story`` /
``epic``, ops teams want ``maintenance`` / ``incident``, HR wants
``onboarding`` / ``offboarding`` etc. Hard-coding the list as a PG ENUM
forced everyone into the dev-team vocabulary; this table lets each org
maintain its own.

Migration 013 seeds five system types matching the old enum
(task / bug / story / epic / subtask) so existing data and UI keep
working. ``is_system`` rows are protected from deletion via the API.
"""

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel

if TYPE_CHECKING:
    from .task import Task


class TaskTypeRef(BaseModel):
    """A user-configurable task type."""

    __tablename__ = "task_types"

    slug: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    color: Mapped[str] = mapped_column(String(20), nullable=False, default="#6b7280")
    icon: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # System rows came from the original enum and cannot be deleted by
    # users — protects historical data integrity. Custom rows added by
    # users have is_system=False and are fully editable.
    is_system: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    tasks: Mapped[list["Task"]] = relationship("Task", back_populates="task_type_ref")
