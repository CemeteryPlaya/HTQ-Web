"""Declarative Base + shared mixins for per-service models.

Every service imports `Base` from this module (or re-exports it from its own
`models/__init__.py`) so admin-aggregator can later reuse the same declarative
metadata when merging schemas.
"""

from datetime import datetime

from sqlalchemy import DateTime, Integer, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base for all per-service models."""


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
