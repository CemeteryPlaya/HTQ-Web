"""Daily rollup of request stats, keyed by (date, project_id, template_id).

Used for the overview tile and the heatmap. Updated UPSERT-style at every
finalization + by a nightly reconciliation actor (see workers/notifications)."""

from datetime import date

from sqlalchemy import Date, Integer, Numeric, PrimaryKeyConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class RequestStatsDaily(Base):
    __tablename__ = "request_stats_daily"

    date: Mapped[date] = mapped_column(Date, nullable=False)
    project_id: Mapped[int] = mapped_column(Integer, nullable=False)
    template_id: Mapped[int] = mapped_column(Integer, nullable=False)

    created: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    approved: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    rejected: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    cancelled: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    sum_approved_amount: Mapped[float] = mapped_column(
        Numeric(18, 2), nullable=False, default=0, server_default="0"
    )
    time_to_decision_seconds_sum: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )

    __table_args__ = (
        PrimaryKeyConstraint("date", "project_id", "template_id", name="pk_request_stats_daily"),
    )
