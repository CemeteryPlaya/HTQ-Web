"""ShareableLink + ShareLinkAudit — public org access links with hashed tokens."""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ShareableLink(Base):
    """One-time / time-limited public org access link.

    The raw token is generated on POST, returned to the creator exactly once,
    and never persisted. We store SHA-256(`token`) in `token_hash`. The legacy
    `token` column lingers as nullable read-only for backfill compatibility
    until a follow-up migration drops it.
    """

    __tablename__ = "hr_shareable_links"
    __table_args__ = (
        CheckConstraint(
            "link_type IN ('one_time','time_limited','permanent_with_expiry')",
            name="ck_link_type",
        ),
        CheckConstraint("max_level >= 1", name="ck_link_max_level"),
        CheckConstraint(
            "default_language IN ('ru','en')",
            name="ck_share_link_default_language",
        ),
        CheckConstraint(
            "target_type IN ('org','employee')",
            name="ck_share_link_target_type",
        ),
        CheckConstraint(
            "(target_type = 'org' AND target_employee_id IS NULL) "
            "OR (target_type = 'employee' AND target_employee_id IS NOT NULL)",
            name="ck_share_link_target_consistency",
        ),
        Index("ix_shareable_links_token_hash", "token_hash", unique=True),
        Index("ix_shareable_links_user", "created_by_user_id"),
        Index("ix_shareable_links_active", "is_active"),
        Index("ix_shareable_links_target_employee", "target_employee_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    # Legacy plaintext token — nullable; new rows leave this NULL. Slated for
    # removal once all pre-migration links have expired.
    token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by_user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str | None] = mapped_column(String(200))
    viewer_label: Mapped[str | None] = mapped_column(String(64))
    watermark_text: Mapped[str | None] = mapped_column(String(128))
    max_level: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    default_language: Mapped[str] = mapped_column(String(2), nullable=False, default="ru")
    visible_units: Mapped[list | None] = mapped_column(JSON)
    link_type: Mapped[str] = mapped_column(String(30), nullable=False, default="one_time")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    opened_by_ip: Mapped[str | None] = mapped_column(String(45))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # 'org' (whole org chart) | 'employee' (single employee card). Defaulted to
    # 'org' to keep legacy rows unchanged after the column was backfilled.
    target_type: Mapped[str] = mapped_column(String(16), nullable=False, default="org")
    # Required when target_type='employee'. No FK so the share-link survives
    # employee soft-delete; the consume path resolves it lazily and 410s if gone.
    target_employee_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )

    def __repr__(self) -> str:
        return (
            f"<ShareableLink(id={self.id}, type='{self.link_type}', "
            f"active={self.is_active})>"
        )


class ShareLinkAudit(Base):
    """Append-only audit trail for shareable link events.

    One row per open/denied/revoked event. INSERT-only; never UPDATE or DELETE
    (CASCADE on link delete is the only way rows leave the table).
    """

    __tablename__ = "hr_share_link_audit"
    __table_args__ = (
        CheckConstraint(
            "action IN ('open','denied_revoked','denied_expired','denied_used',"
            "'denied_unknown','revoked','created')",
            name="ck_share_link_audit_action",
        ),
        Index("ix_share_link_audit_link", "link_id", "occurred_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    link_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("hr_shareable_links.id", ondelete="CASCADE"),
        nullable=False,
    )
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    ip: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(String(64))
