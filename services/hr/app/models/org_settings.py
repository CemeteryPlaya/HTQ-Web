"""OrgSettings — key-value configuration table for org behaviour."""

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from sqlalchemy import DateTime, func


class OrgSettings(Base):
    __tablename__ = "hr_org_settings"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    value: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self) -> str:
        return f"<OrgSettings({self.key}={self.value!r})>"
