"""Watchers — users who follow a request without an approval role."""

from sqlalchemy import ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class RequestWatcher(Base):
    __tablename__ = "request_watchers"

    request_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("request_instances.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(Integer, primary_key=True)
