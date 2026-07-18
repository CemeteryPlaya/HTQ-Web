"""Department replica model for task service."""

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Department(Base):
    """Denormalized department data — replica synced from hr-service.

    Named `task_departments` to avoid colliding with `hr_departments` in the
    same `public` schema.
    """
    __tablename__ = "task_departments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
