"""User replica — synced from user-service / hr-service via Redis pub/sub."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class RequestUser(Base):
    """Denormalized user data. Named ``request_users`` to avoid collision
    with auth.users in a shared search_path. Append-only on delete: we keep
    rows so approval history stays attributable (spec §2.8)."""

    __tablename__ = "request_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    username: Mapped[str] = mapped_column(String(150), nullable=False, default="")
    email: Mapped[str] = mapped_column(String(254), nullable=False, default="")
    first_name: Mapped[str] = mapped_column(String(150), nullable=False, default="")
    last_name: Mapped[str] = mapped_column(String(150), nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_elevated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    deactivated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    @property
    def full_name(self) -> str:
        name = f"{self.first_name} {self.last_name}".strip()
        return name or self.username
