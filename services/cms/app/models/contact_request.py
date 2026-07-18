"""ContactRequest model — mirrors Django backend/media_manager/models.py:ContactRequest.

Legacy Django table: ``mainView_contactrequest`` (public schema).
Target table: ``cms.contact_requests``. ``replied_by_id`` is FK-less (Integer)
because the User table lives in the ``auth`` schema owned by user-service.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ContactRequest(Base):
    __tablename__ = "contact_requests"
    __table_args__ = {"schema": "cms"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    first_name: Mapped[str] = mapped_column(
        String(150), nullable=False, default="", server_default=""
    )
    last_name: Mapped[str] = mapped_column(
        String(150), nullable=False, default="", server_default=""
    )
    email: Mapped[str] = mapped_column(String(254), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    handled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false", index=True
    )
    replied_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    replied_by_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    reply_message: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ContactRequest id={self.id} email={self.email!r} handled={self.handled}>"
