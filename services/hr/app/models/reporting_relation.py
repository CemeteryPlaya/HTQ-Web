"""ReportingRelation — subordination matrix cell."""

from datetime import date

from sqlalchemy import CheckConstraint, Date, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel


class ReportingRelation(BaseModel):
    __tablename__ = "hr_reporting_relations"
    __table_args__ = (
        UniqueConstraint(
            "superior_position_id", "subordinate_position_id", "relation_type",
            name="uq_reporting_relation",
        ),
        CheckConstraint("superior_position_id != subordinate_position_id", name="ck_no_self_relation"),
        CheckConstraint("relation_type IN ('direct','functional','project')", name="ck_relation_type"),
        Index("ix_reporting_superior", "superior_position_id"),
        Index("ix_reporting_subordinate", "subordinate_position_id"),
    )

    superior_position_id: Mapped[int] = mapped_column(
        ForeignKey("hr_positions.id", ondelete="CASCADE"), nullable=False
    )
    subordinate_position_id: Mapped[int] = mapped_column(
        ForeignKey("hr_positions.id", ondelete="CASCADE"), nullable=False
    )
    relation_type: Mapped[str] = mapped_column(String(20), nullable=False, default="direct")
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date)

    def __repr__(self) -> str:
        return (
            f"<ReportingRelation(sup={self.superior_position_id}, "
            f"sub={self.subordinate_position_id}, type='{self.relation_type}')>"
        )
