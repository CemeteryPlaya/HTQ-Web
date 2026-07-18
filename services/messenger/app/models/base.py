"""Declarative Base and Mixins."""

from datetime import datetime

from sqlalchemy import DateTime, Integer, MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.settings import settings


class Base(DeclarativeBase):
    """Declarative base for all per-service models."""

    metadata = MetaData(schema=settings.db_schema)


class TimestampMixin:
    """created_at / updated_at timestamps — server-side defaults."""

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


class IntIdMixin:
    """Integer PK named ``id``."""

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
