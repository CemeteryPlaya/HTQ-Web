"""Taxonomy models for CMS news: Category, Tag, news_tags join.

Kept in their own module so admin views and schemas can import without
pulling the full News graph.
"""

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Table, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


news_tags = Table(
    "news_tags",
    Base.metadata,
    Column("news_id", ForeignKey("cms.news.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", ForeignKey("cms.tags.id", ondelete="CASCADE"), primary_key=True),
    schema="cms",
)


class Category(Base):
    __tablename__ = "categories"
    __table_args__ = {"schema": "cms"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(String(120), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(String(500), default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Category id={self.id} slug={self.slug!r}>"


class Tag(Base):
    __tablename__ = "tags"
    __table_args__ = {"schema": "cms"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(String(80), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Tag id={self.id} slug={self.slug!r}>"
