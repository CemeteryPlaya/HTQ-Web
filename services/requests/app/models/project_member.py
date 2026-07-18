"""Project membership — who can administer / participate in a project."""

import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class ProjectMemberRole(str, enum.Enum):
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"


class RequestProjectMember(Base):
    __tablename__ = "request_project_members"

    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("request_projects.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("request_users.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[ProjectMemberRole] = mapped_column(
        Enum(ProjectMemberRole, native_enum=False, length=20),
        nullable=False,
        default=ProjectMemberRole.MEMBER,
    )
    granted_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    project: Mapped["RequestProject"] = relationship("RequestProject", back_populates="members")
