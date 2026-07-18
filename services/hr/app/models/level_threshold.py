"""LevelThreshold — configurable mapping of weight ranges to hierarchy levels."""

from sqlalchemy import CheckConstraint, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel


class LevelThreshold(BaseModel):
    __tablename__ = "hr_level_thresholds"
    __table_args__ = (
        CheckConstraint("weight_from <= weight_to", name="ck_threshold_range"),
        CheckConstraint("level_number >= 1", name="ck_threshold_level_positive"),
        Index("ix_hr_level_thresholds_level", "level_number", unique=True),
    )

    level_number: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    weight_from: Mapped[int] = mapped_column(Integer, nullable=False)
    weight_to: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str | None] = mapped_column(String(100))
    color: Mapped[str | None] = mapped_column(String(7))

    def __repr__(self) -> str:
        return f"<LevelThreshold(level={self.level_number}, {self.weight_from}–{self.weight_to}, '{self.label}')>"
