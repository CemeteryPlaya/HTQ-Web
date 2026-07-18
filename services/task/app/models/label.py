"""Label model for task categorization."""

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel


class Label(BaseModel):
    """Label/tag for tasks."""

    __tablename__ = "labels"

    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    color: Mapped[str] = mapped_column(
        String(7), nullable=False, default="#808080"
    )  # Hex color

    # Relationships
    tasks = relationship(
        "Task",
        secondary="task_labels",
        back_populates="labels",
    )
