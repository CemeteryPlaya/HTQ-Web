"""Department replica — synced from hr-service via Redis pub/sub."""

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class RequestDepartment(Base):
    """Denormalized department data. Named ``request_departments`` to avoid
    collision with other services' tables in a shared search_path."""

    __tablename__ = "request_departments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    parent_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    head_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
