"""FileVariant — derived renditions (thumbnails, posters, previews) of an original file.

A variant is always tied to a parent ``FileMetadata`` row via ``file_id``;
when the parent is deleted the variants are dropped along with it. We keep
variants in a separate table (rather than self-referencing FileMetadata) so
that listing/auditing the originals is not polluted by every thumbnail and
so that ``ON DELETE CASCADE`` cleans up cleanly.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.file_metadata import FileMetadata


class FileVariant(Base):
    __tablename__ = "file_variants"
    __table_args__ = (
        UniqueConstraint("file_id", "variant", name="uq_file_variants_file_variant"),
        {"schema": "media"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("media.file_metadata.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    variant: Mapped[str] = mapped_column(String(16), nullable=False)
    path: Mapped[str] = mapped_column(String(1024), nullable=False, unique=True)
    size: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    mime: Mapped[str] = mapped_column(String(255), nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    file: Mapped["FileMetadata"] = relationship("FileMetadata", back_populates="variants")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<FileVariant file_id={self.file_id} variant={self.variant!r} {self.width}x{self.height}>"
