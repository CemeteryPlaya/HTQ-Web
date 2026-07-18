"""News model — `cms.news` table.

Carries the editorial article: title/slug, rich-text content (HTML produced by
the WYSIWYG editor on the frontend), cover image URL, taxonomy (category +
tags), author, lifecycle status (`draft|scheduled|published|archived`), and
scheduling.

Legacy fields kept for transitional compatibility:
- ``summary`` — superseded by ``excerpt`` but mirrored on writes.
- ``category`` (string) — superseded by ``category_id`` FK; old rows that
  predate the FK still surface their string value.
- ``published`` (bool) — kept as a denormalized mirror of
  ``status='published'``; a database trigger keeps the two in sync (see
  alembic 0003_news_taxonomy.py).
"""

from datetime import datetime
from enum import Enum as PyEnum
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.taxonomy import Category, Tag, news_tags


class NewsStatus(str, PyEnum):
    DRAFT = "draft"
    SCHEDULED = "scheduled"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class News(Base):
    __tablename__ = "news"
    __table_args__ = {"schema": "cms"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    slug: Mapped[str] = mapped_column(String(320), nullable=False, unique=True, index=True)

    # Editorial
    excerpt: Mapped[str] = mapped_column(String(500), default="", server_default="")
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    content: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    image: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # Taxonomy
    category: Mapped[str] = mapped_column(
        String(100), nullable=False, default="", server_default="", index=True,
    )
    category_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("cms.categories.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    author_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)

    # Lifecycle
    status: Mapped[NewsStatus] = mapped_column(
        Enum(
            NewsStatus,
            name="news_status",
            schema="cms",
            values_callable=lambda enum: [member.value for member in enum],
        ),
        default=NewsStatus.DRAFT,
        server_default=NewsStatus.DRAFT.value,
        nullable=False,
        index=True,
    )
    published: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false", index=True,
    )
    published_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True,
    )
    scheduled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relations
    category_ref: Mapped[Optional["Category"]] = relationship(lazy="joined")
    tags: Mapped[list["Tag"]] = relationship(secondary=news_tags, lazy="selectin")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<News id={self.id} slug={self.slug!r} status={self.status}>"
