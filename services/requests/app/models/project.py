"""Project stub — local to requests-service until a dedicated project-service
exists. Named ``request_projects`` to avoid colliding with task-service's
``public.projects`` in the shared schema."""

import enum
from datetime import date

from sqlalchemy import Date, Enum, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel


class ProjectStatus(str, enum.Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class RequestProject(BaseModel):
    __tablename__ = "request_projects"

    name: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    status: Mapped[ProjectStatus] = mapped_column(
        Enum(ProjectStatus, native_enum=False, length=20),
        nullable=False,
        default=ProjectStatus.ACTIVE,
        server_default=ProjectStatus.ACTIVE.value,
    )
    color: Mapped[str] = mapped_column(String(20), nullable=False, default="#3b82f6", server_default="#3b82f6")
    budget_limit: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="KZT", server_default="KZT")
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    owner_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("request_users.id", ondelete="SET NULL"), index=True
    )
    department_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("request_departments.id", ondelete="SET NULL"), index=True
    )

    members: Mapped[list["RequestProjectMember"]] = relationship(
        "RequestProjectMember", back_populates="project", cascade="all, delete-orphan"
    )
