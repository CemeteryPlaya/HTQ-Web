"""User-owned content items.

Mirrors backend/mainView/models.py:Item — personal notes/drafts owned by a user.
Each Item belongs to exactly one user (owner_id → users.id).
"""

from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)

from app.models.user import Base


class Item(Base):
    __tablename__ = "items"
    __table_args__ = (
        Index("ix_items_owner_id", "owner_id"),
        Index("ix_items_created_at", "created_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=False, default="")
    owner_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
