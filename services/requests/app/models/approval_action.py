"""A single approver's slot on a workflow node (one row per assignee)."""

import enum
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class ApprovalActionType(str, enum.Enum):
    APPROVE = "approve"
    REJECT = "reject"
    REQUEST_CHANGES = "request_changes"
    DELEGATE = "delegate"
    AUTO_SKIP = "auto_skip"


class ApprovalAction(Base):
    __tablename__ = "request_approval_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    request_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("request_instances.id", ondelete="CASCADE"), nullable=False, index=True
    )
    node_id: Mapped[str] = mapped_column(String(64), nullable=False)
    step_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    approver_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    action: Mapped[str | None] = mapped_column(String(20), nullable=True)
    comment: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    acted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reminded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reminders_sent: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    instance: Mapped["RequestInstance"] = relationship("RequestInstance", back_populates="actions")
