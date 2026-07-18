"""Position (должность) model."""

from sqlalchemy import ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel


class Position(BaseModel):
    __tablename__ = "hr_positions"
    __table_args__ = (
        # weight is globally unique across all positions
        Index("ix_hr_positions_weight", "weight"),
        Index("ix_hr_positions_level", "level"),
        Index("ix_hr_positions_is_system", "is_system"),
    )

    title: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    department_id: Mapped[int] = mapped_column(ForeignKey("hr_departments.id"))
    grade: Mapped[int] = mapped_column(Integer, default=1)  # 1–10
    description: Mapped[str | None] = mapped_column(Text)
    requirements: Mapped[dict | None] = mapped_column(JSON)
    is_active: Mapped[bool] = mapped_column(default=True)

    # Weight system: lower weight = higher in hierarchy (0 = top)
    weight: Mapped[int] = mapped_column(Integer, nullable=False, default=100, unique=True)
    # Level cached from hr_level_thresholds; recomputed on weight change
    level: Mapped[int] = mapped_column(Integer, nullable=False, default=2)

    # System positions are baseline org units (seeded) that cannot be
    # renamed or deleted via the UI. Weight / department / permissions
    # are still editable.
    is_system: Mapped[bool] = mapped_column(default=False, nullable=False)
    # Explicit permission matrix. When set, takes precedence over the
    # title-based HR-level heuristic in ``app.auth.hr_access``.
    # Shape: ``{"hr_level": "junior|middle|senior|lead", "permissions": [str, ...]}``
    permissions: Mapped[dict | None] = mapped_column(JSON)

    def __repr__(self) -> str:
        return f"<Position(id={self.id}, title='{self.title}', weight={self.weight}, level={self.level})>"
