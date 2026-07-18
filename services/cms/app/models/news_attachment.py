"""NewsAttachment model — files attached to a news post (binary assets in S3).

The cover image is also tracked here when uploaded via ``POST /news/{id}/cover``;
it's marked with ``role='cover'`` and the post's ``image`` column gets the
public S3 path so the existing list/detail responses keep working.
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class NewsAttachment(Base):
    __tablename__ = "news_attachments"
    __table_args__ = {"schema": "cms"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    news_id: Mapped[int] = mapped_column(
        ForeignKey("cms.news.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(
        String(20), nullable=False, default="attachment", server_default="attachment"
    )  # attachment | cover
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    content_type: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    uploaded_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
