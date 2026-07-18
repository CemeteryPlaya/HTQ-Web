"""FileMetadata model — tracks uploaded files."""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class FileMetadata(Base):
    __tablename__ = "file_metadata"
    __table_args__ = {"schema": "media"}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    path: Mapped[str] = mapped_column(String(1024), nullable=False, unique=True)
    original_filename: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    owner_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    size: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    mime: Mapped[str] = mapped_column(String(255), nullable=False, default="application/octet-stream")
    storage_backend: Mapped[str] = mapped_column(String(16), nullable=False, default="local")
    is_public: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    # Phase 1: classification + integrity
    sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(
        String(16), nullable=False, default="other", server_default="other", index=True
    )
    scope: Mapped[str] = mapped_column(
        String(32), nullable=False, default="generic", server_default="generic", index=True
    )
    width: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    height: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    variants: Mapped[list["FileVariant"]] = relationship(
        "FileVariant",
        back_populates="file",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<FileMetadata id={self.id} path={self.path!r} size={self.size}>"
