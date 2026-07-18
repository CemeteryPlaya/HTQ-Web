"""User replica model for task service."""

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class User(Base):
    """Denormalized user data — replica synced from user-service.

    Named `task_users` so it doesn't collide with `auth.users` when the
    role-level search_path falls through to auth.
    """
    __tablename__ = "task_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    username: Mapped[str] = mapped_column(String(150), nullable=False)
    email: Mapped[str] = mapped_column(String(254), nullable=False, default="")
    first_name: Mapped[str] = mapped_column(String(150), nullable=False, default="")
    last_name: Mapped[str] = mapped_column(String(150), nullable=False, default="")
    # Mirrored from user.avatar_url via the user.upserted event so the
    # notification API can render the sender's photo without a S2S call.
    avatar_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    department_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("task_departments.id", ondelete="SET NULL"), index=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    department = relationship("Department")
