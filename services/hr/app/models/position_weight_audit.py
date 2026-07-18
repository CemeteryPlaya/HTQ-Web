"""Append-only audit log for position weight and level changes."""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class PositionWeightAudit(Base):
    __tablename__ = "hr_position_weight_audit"
    __table_args__ = (
        Index("ix_hr_position_weight_audit_position", "position_id", "changed_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    position_id: Mapped[int] = mapped_column(
        ForeignKey("hr_positions.id", ondelete="CASCADE"),
        nullable=False,
    )
    old_weight: Mapped[int | None] = mapped_column(Integer)
    new_weight: Mapped[int | None] = mapped_column(Integer)
    old_level: Mapped[int | None] = mapped_column(Integer)
    new_level: Mapped[int | None] = mapped_column(Integer)
    changed_by: Mapped[int | None] = mapped_column(Integer)
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    reason: Mapped[str | None] = mapped_column(String(64))
