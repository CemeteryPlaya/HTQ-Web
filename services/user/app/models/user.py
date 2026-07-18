"""
SQLAlchemy models for the User/Identity Service.

Replaces Django's auth.User + mainView.Profile with a single unified model.
This service is the JWT authority for the entire platform.
"""

import enum
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class UserStatus(str, enum.Enum):
    """User account status."""
    PENDING = "pending"       # is_active=False, awaiting admin approval
    ACTIVE = "active"         # can login
    SUSPENDED = "suspended"   # admin-disabled
    REJECTED = "rejected"     # registration denied


class User(Base):
    """
    Unified user model — combines Django's auth.User + mainView.Profile.

    JWT tokens reference this model by ID. All other services
    (HR, Tasks, etc.) reference users by this ID.
    """
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("email", name="uq_users_email"),
        Index("ix_users_email", "email"),
        Index("ix_users_username", "username"),
        Index("ix_users_status", "status"),
    )

    # Primary key — integer, auto-increment
    # Migrating from Django's auth.User.id — same values during migration
    id = Column(Integer, primary_key=True, autoincrement=True)

    # Authentication
    username = Column(String(150), unique=True, nullable=False)
    email = Column(String(254), unique=True, nullable=False)
    password_hash = Column(String(256), nullable=False)

    # Identity
    first_name = Column(String(150), nullable=False, default="")
    last_name = Column(String(150), nullable=False, default="")
    patronymic = Column(String(100), nullable=False, default="")
    display_name = Column(String(100), nullable=False, default="")

    # Profile
    bio = Column(Text, nullable=False, default="")
    phone = Column(String(30), nullable=False, default="")
    avatar_url = Column(String(500), nullable=True)

    # Settings (stored as JSON — replaces Django JSONField)
    settings = Column(JSON, nullable=False, default=dict)

    # Status & permissions
    status = Column(
        Enum(UserStatus, values_callable=lambda e: [x.value for x in e]),
        nullable=False,
        default=UserStatus.PENDING,
    )
    is_staff = Column(Boolean, nullable=False, default=False)
    is_superuser = Column(Boolean, nullable=False, default=False)

    # HR-managed flag — user must change password on next login
    must_change_password = Column(Boolean, nullable=False, default=False)

    # Timestamps
    date_joined = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    last_login = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self) -> str:
        return f"<User(id={self.id}, username='{self.username}', status='{self.status}')>"
