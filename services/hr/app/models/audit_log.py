"""Audit log model — who changed what and when."""

from sqlalchemy import ForeignKey, Index, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel


class AuditLog(BaseModel):
    __tablename__ = "hr_audit_log"
    __table_args__ = (
        Index("ix_audit_log_entity", "entity_type", "entity_id"),
    )

    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)  # employee | department | …
    entity_id: Mapped[int] = mapped_column(nullable=False)
    action: Mapped[str] = mapped_column(String(20), nullable=False)  # create | update | delete
    old_values: Mapped[dict | None] = mapped_column(JSON)
    new_values: Mapped[dict | None] = mapped_column(JSON)
    changed_by: Mapped[int] = mapped_column(ForeignKey("hr_employees.id"))
    ip_address: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(String(500))

    def __repr__(self) -> str:
        return f"<AuditLog(id={self.id}, entity={self.entity_type}:{self.entity_id}, action='{self.action}')>"
