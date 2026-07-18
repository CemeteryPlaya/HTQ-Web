"""Request instance — a submitted form progressing through its workflow."""

import enum
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel

JSON_VARIANT = JSON().with_variant(JSONB(), "postgresql")


class RequestStatus(str, enum.Enum):
    DRAFT = "draft"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    RETURNED = "returned"


class RequestInstance(BaseModel):
    __tablename__ = "request_instances"

    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    template_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("request_form_templates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    template_version_id: Mapped[int] = mapped_column(Integer, nullable=False)
    project_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("request_projects.id", ondelete="SET NULL"), index=True
    )
    initiator_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False, default="", server_default="")
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=RequestStatus.DRAFT.value, server_default="draft", index=True
    )
    current_node_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    form_values_json: Mapped[dict] = mapped_column(JSON_VARIANT, nullable=False, default=dict)
    total_amount: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    requires_admin_attention: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    actions: Mapped[list["ApprovalAction"]] = relationship(
        "ApprovalAction", back_populates="instance", cascade="all, delete-orphan"
    )
